import logging
import collections
import urllib2
import fnmatch
import time

import dynamo.utils.interface.webservice as webservice
from dynamo.dataformat import Configuration, Block

LOG = logging.getLogger(__name__)

class WebReplicaLock(object):
    """
    Dataset lock read from www sources.
    Sets one attr:
      locked_blocks:   {site: set of blocks}
    """

    produces = ['locked_blocks']

    # content types
    LIST_OF_DATASETS, CMSWEB_LIST_OF_DATASETS, SITE_TO_DATASETS = range(3)

    def __init__(self, config):
        self._sources = {} # {name: (RESTService, content type, site pattern, lock of locks)}

        for name, source_config in config.sources.items():
            self.add_source(name, source_config, config.auth)

    def add_source(self, name, config, auth_config):
        rest_config = Configuration()
        rest_config.url_base = config.url
        rest_config.accept = config.get('data_type', 'application/json')
        if config.auth == 'noauth':
            rest_config.auth_handler = 'None'
        else:
            auth = auth_config[config.auth]
            rest_config.auth_handler = auth.auth_handler
            rest_config.auth_handler_conf = Configuration(auth.get('auth_handler_conf', {}))

        content_type = getattr(WebReplicaLock, config.content_type)
        site_pattern = config.get('sites', None)
        lock_url = config.get('lock_url', None)

        self._sources[name] = (webservice.RESTService(rest_config), content_type, site_pattern, lock_url)

    def update(self, inventory):
        for dataset in inventory.datasets.itervalues():
            try:
                dataset.attr.pop('locked_blocks')
            except KeyError:
                pass

        for source, content_type, site_pattern, lock_url in self._sources.itervalues():        
            if lock_url is not None:
                # check that the lock files themselves are not locked
                while True:
                    # Hacky but this is temporary any way
                    opener = urllib2.build_opener(webservice.HTTPSCertKeyHandler(Configuration()))
                    opener.addheaders.append(('Accept', 'application/json'))
                    request = urllib2.Request(lock_url)
                    try:
                        opener.open(request)
                    except urllib2.HTTPError as err:
                        if err.code == 404:
                            # file not found -> no lock
                            break
                        else:
                            raise
        
                    LOG.info('Lock files are being produced. Waiting 60 seconds.')
                    time.sleep(60)

            LOG.info('Retrieving lock information from %s', source.url_base)

            data = source.make_request()

            if content_type == WebReplicaLock.LIST_OF_DATASETS:
                # simple list of datasets
                for dataset_name in data:
                    if dataset_name is None:
                        LOG.debug('Dataset name None found in %s', source.url_base)
                        continue

                    try:
                        dataset = inventory.datasets[dataset_name]
                    except KeyError:
                        LOG.debug('Unknown dataset %s in %s', dataset_name, source.url_base)
                        continue

                    if dataset.replicas is None:
                        continue

                    try:
                        locked_blocks = dataset.attr['locked_blocks']
                    except KeyError:
                        locked_blocks = dataset.attr['locked_blocks'] = {}

                    for replica in dataset.replicas:
                        if site_pattern is not None and not fnmatch.fnmatch(replica.site.name, site_pattern):
                            continue

                        if replica.site in locked_blocks:
                            locked_blocks[replica.site].update(brep.block for brep in replica.block_replicas)
                        else:
                            locked_blocks[replica.site] = set(brep.block for brep in replica.block_replicas)

            elif content_type == WebReplicaLock.CMSWEB_LIST_OF_DATASETS:
                # data['result'] -> simple list of datasets
                for dataset_name in data['result']:
                    if dataset_name is None:
                        LOG.debug('Dataset name None found in %s', source.url_base)
                        continue

                    try:
                        dataset = inventory.datasets[dataset_name]
                    except KeyError:
                        LOG.debug('Unknown dataset %s in %s', dataset_name, source.url_base)
                        continue

                    if dataset.replicas is None:
                        continue

                    try:
                        locked_blocks = dataset.attr['locked_blocks']
                    except KeyError:
                        locked_blocks = dataset.attr['locked_blocks'] = {}

                    for replica in dataset.replicas:
                        if site_pattern is not None and not fnmatch.fnmatch(replica.site.name, site_pattern):
                            continue

                        if replica.site in locked_blocks:
                            locked_blocks[replica.site].update(brep.block for brep in replica.block_replicas)
                        else:
                            locked_blocks[replica.site] = set(brep.block for brep in replica.block_replicas)
                
            elif content_type == WebReplicaLock.SITE_TO_DATASETS:
                # data = {site: {dataset: info}}
                for site_name, objects in data.items():
                    try:
                        site = inventory.sites[site_name]
                    except KeyError:
                        LOG.debug('Unknown site %s in %s', site_name, source.url_base)
                        continue

                    for object_name, info in objects.items():
                        if not info['lock']:
                            LOG.debug('Object %s is not locked at %s', object_name, site_name)
                            continue

                        if '#' in object_name:
                            dataset_name, block_real_name = object_name.split('#')
                        else:
                            dataset_name = object_name
                            block_real_name = None

                        try:
                            dataset = inventory.datasets[dataset_name]
                        except KeyError:
                            LOG.debug('Unknown dataset %s in %s', dataset_name, source.url_base)
                            continue

                        replica = site.find_dataset_replica(dataset)
                        if replica is None:
                            LOG.debug('Replica of %s is not at %s in %s', dataset_name, site_name, source.url_base)
                            continue

                        if block_real_name is None:
                            blocks = list(dataset.blocks)
                        else:
                            block = dataset.find_block(Block.to_internal_name(block_real_name))
                            if block is None:
                                LOG.debug('Unknown block %s of %s in %s', block_real_name, dataset_name, source.url_base)
                                continue

                            blocks = [block]

                        try:
                            locked_blocks = dataset.attr['locked_blocks']
                        except KeyError:
                            locked_blocks = dataset.attr['locked_blocks'] = {}
    
                        if site in locked_blocks:
                            locked_blocks[site].update(blocks)
                        else:
                            locked_blocks[site] = set(blocks)
