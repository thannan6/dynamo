import time
import datetime
import collections
import logging
import multiprocessing

from utils.interface.popdb import PopDB
from utils.interface.mysql import MySQL

# last_access is unix time
ReplicaAccess = collections.namedtuple('ReplicaAccess', ['rank', 'num_access', 'tot_cpu', 'last_access'])

LOG = logging.getLogger(__name__)

class CRABAccessHistory(object):
    """
    Sets two demand values:
      global_usage_rank:  float value
      local_usage:        {site: ReplicaAccess}
    """

    def __init__(self, config):
        self.max_back_query = config.max_back_query

        self._popdb = PopDB(config.popdb.config)
        self._store = MySQL(config.store.config)

    def update(self, inventory):
        records, last_update = self._get_stored_records(inventory)
        source_records = self._get_source_records(inventory, last_update)
        for replica, accesses in source_records.iteritems():
            try:
                records[replica].update(accesses)
            except KeyError:
                records[replica] = dict(accesses)

        self._save_records(source_records)

        self._compute(inventory, records)

    def _get_stored_records(self, inventory):
        """
        Get the replica access data from DB.
        @param inventory  DynamoInventory
        @return  {replica: {date: (number of access, total cpu time)}}
        """

        # pick up all accesses that are less than 2 years old
        # old accesses will eb removed automatically next time the access information is saved from memory
        sql = 'SELECT s.`name`, d.`name`, YEAR(a.`date`), MONTH(a.`date`), DAY(a.`date`), a.`access_type`+0, a.`num_accesses`, a.`cputime` FROM `dataset_accesses` AS a'
        sql += ' INNER JOIN `sites` AS s ON s.`id` = a.`site_id`'
        sql += ' INNER JOIN `datasets` AS d ON d.`id` = a.`dataset_id`'
        sql += ' WHERE a.`date` > DATE_SUB(NOW(), INTERVAL 2 YEAR) ORDER BY s.`id`, d.`id`, a.`date`'

        all_accesses = {}
        num_records = 0

        # little speedup by not repeating lookups for the same replica
        current_site_name = ''
        site_exists = True
        current_dataset_name = ''
        dataset_exists = True
        replica = None
        for site_name, dataset_name, year, month, day, access_type, num_accesses, cputime in self._store.xquery(sql):
            num_records += 1

            if site_name == current_site_name:
                if not site_exists:
                    continue
            else:
                current_site_name = site_name

                current_dataset_name = ''
                dataset_exists = True
                replica = None

                try:
                    site = inventory.sites[site_name]
                except KeyError:
                    site_exists = False
                    continue
                else:
                    site_exists = True

            if dataset_name == current_dataset_name:
                if not dataset_exists:
                    continue
            else:
                current_dataset_name = dataset_name

                try:
                    dataset = inventory.datasets[dataset_name]
                except KeyError:
                    dataset_exists = False
                    continue
                else:
                    dataset_exists = True

                replica = site.find_dataset_replica(dataset)
                if replica is not None:
                    accesses = all_accesses[replica] = {}

            if replica is None:
                continue

            date = datetime.date(year, month, day)
            accesses[date] = (num_accesses, cputime)

        last_update = self._store.query('SELECT UNIX_TIMESTAMP(`dataset_accesses_last_update`) FROM `system`')[0]

        LOG.info('Loaded %d replica access data. Last update on %s UTC', num_records, time.strftime('%Y-%m-%d', time.gmtime(last_update)))

        return all_accesses, last_update

    def _save_records(self, records):
        """
        Save the newly fetched access records.
        @param records  {replica: {date: (number of access, total cpu time)}}
        """

        site_id_map = {}
        self._store._make_map('sites', set(r.site for r in records.iterkeys()), site_id_map, None)
        dataset_id_map = {}
        self._store._make_map('datasets', set(r.dataset for r in records.iterkeys()), dataset_id_map, None)

        fields = ('dataset_id', 'site_id', 'date', 'access_type', 'num_accesses', 'cputime')

        data = []
        for replica, entries in access_list.iteritems():
            dataset_id = dataset_id_map[replica.dataset]
            site_id = site_id_map[replica.site]

            for date, (num_accesses, cputime) in entries.iteritems():
                data.append((dataset_id, site_id, date.strftime('%Y-%m-%d'), 'local', num_accesses, cputime))

        self._store.insert_many('dataset_accesses', fields, None, data, do_update = True)

        # remove old entries
        self._store.query('DELETE FROM `dataset_accesses` WHERE `date` < DATE_SUB(NOW(), INTERVAL 2 YEAR)')
        self._store.query('UPDATE `system` SET `dataset_accesses_last_update` = NOW()')

    def _get_source_records(self, inventory, last_update):
        """
        Get the replica access data from PopDB.
        @param inventory  DynamoInventory
        @param date       datetime.datetime instance
        @return  {replica: {date: (number of access, total cpu time)}}
        """

        start_time = max(last_update, (time.time() - 3600 * 24 * self.max_back_query))
        start_date = datetime.date(*time.gmtime(start_time)[:3])

        days_to_query = []

        utctoday = datetime.date(*time.gmtime()[:3])
        date = start_date
        while date <= utctoday: # get records up to today
            days_to_query.append(date)
            date += datetime.timedelta(1) # one day

        LOG.info('Updating dataset access info from %s to %s', start_date.strftime('%Y-%m-%d'), utctoday.strftime('%Y-%m-%d'))

        all_accesses = {}

        #TODO: parallelise
        for site in inventory.sites.itervalues():
            for date in days_to_query:
                site_record = self._get_site_record(site, inventory.datasets, date)

                for replica, naccess, cputime in site_record:
                    if replica not in all_accesses:
                        all_accesses[replica] = []

                    all_accesses[replica][date] = (naccess, cputime)

        return all_accesses

    def _get_site_record(self, site, datasets, date):
        """
        Get the replica access data on a single site from PopDB.
        @param site       Site
        @param datasets   datasets dictionary of inventory
        @param date       datetime.date
        @return [(replica, number of access, total cpu time)]
        """

        if site.name.startswith('T0'):
            return []
        elif site.name.startswith('T1') and site.name.count('_') > 2:
            nameparts = site.name.split('_')
            sitename = '_'.join(nameparts[:3])
            service = 'popularity/DSStatInTimeWindow/' # the trailing slash is apparently important
        elif site.name == 'T2_CH_CERN':
            sitename = site.name
            service = 'xrdpopularity/DSStatInTimeWindow'
        else:
            sitename = site.name
            service = 'popularity/DSStatInTimeWindow/'

        datestr = date.strftime('%Y-%m-%d')
        result = self._popdb.make_request(service, ['sitename=' + sitename, 'tstart=' + datestr, 'tstop=' + datestr])

        records = []
        
        for ds_entry in result:
            try:
                dataset = datasets[ds_entry['COLLNAME']]
            except KeyError:
                continue

            replica = site.find_dataset_replica(dataset)
            if replica is None:
                continue

            records.append((replica, int(ds_entry['NACC']), float(ds_entry['TOTCPU'])))

        return records

    def _compute(self, inventory, all_accesses):
        """
        Set the dataset usage rank based on access list.
        Following the IntelROCCS implementation for local rank:
        datasetRank = (1-used)*(now-creationDate)/(60*60*24) + \
            used*( (now-lastAccessed)/(60*60*24)-nAccessed) - size/1000
        nAccessed is NACC normalized by size (in GB).
        @param inventory   DynamoInventory
        @param all_accesses {replica: {date: (number of access, cpu time)}}
        """

        now = time.time()
        today = datetime.datetime.utcfromtimestamp(now).date()

        for dataset in inventory.datasets.itervalues():
            local_usage = dataset.demand['local_usage'] = {} # {site: ReplicaAccess}

            for replica in dataset.replicas:
                size = replica.size(physical = False) * 1.e-9

                try:
                    accesses = all_accesses[replica]
                except KeyError:
                    accesses = {}
                    last_used = 0
                    num_access = 0
                    tot_cpu = 0.
                else:
                    last_access = max(accesses.iterkeys())
                    # mktime returns expects the local time but the timetuple we pass is for UTC. subtracting time.timezone
                    last_used = time.mktime(last_access.timetuple()) - time.timezone
                    num_access = sum(e[0] for e in accesses.itervalues())
                    tot_cpu = sum(e[1] for e in accesses.itervalues())

                if num_access == 0:
                    local_rank = (now - replica.last_block_created()) / (24. * 3600.)
                elif size > 0.:
                    local_rank = (today - last_access).days - num_access / size
                else:
                    local_rank = (today - last_access).days

                local_rank -= size * 1.e-3

                local_usage[replica.site] = ReplicaAccess(local_rank, num_access, tot_cpu, last_used)

            global_rank = sum(usage.rank for usage in local_usage.values())

            if len(dataset.replicas) != 0:
                global_rank /= len(dataset.replicas)

            dataset.demand['global_usage_rank'] = global_rank
