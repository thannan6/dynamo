import logging
import math

from dynamo.dataformat import Dataset
from base import BaseHandler

LOG = logging.getLogger(__name__)

class PopularityHandler(BaseHandler):
    """
    Request replication of datasets using information from dataset_request dataset attr.
    """

    def __init__(self, config):
        BaseHandler.__init__(self, 'Popularity')
        self.required_attrs = ['request_weight']

        self.source_groups = set(config.source_groups)
        self.max_dataset_size = config.max_dataset_size * 1.e+12
        self.max_replication = config.max_replication
        self.request_to_replica_threshold = config.request_to_replica_threshold

        self._datasets = []

    def get_requests(self, inventory, history, policy): # override
        self._datasets = []
        requests = []

        for dataset in inventory.datasets.itervalues():
            try:
                request_weight = dataset.attr['request_weight']
            except KeyError:
                continue

            LOG.debug('Dataset %s request weight %f', dataset.name, request_weight)

            dataset_in_source_groups = False
            for dr in dataset.replicas:
                for br in dr.block_replicas:
                    if br.group.name in self.source_groups:
                        # found at least one block/dataset replica in source groups
                        # therefore it is a legit dataset to replicate
                        dataset_in_source_groups = True

            if not dataset_in_source_groups:
                continue

            if request_weight <= 0.:
                continue

            if dataset.size > self.max_dataset_size:
                continue

            self._datasets.append(dataset)

            num_requests = min(self.max_replication, int(math.ceil(request_weight / self.request_to_replica_threshold))) - len(dataset.replicas)
            if num_requests <= 0:
                continue

            LOG.debug('Requesting %d copies of %s', num_requests, dataset.name)

            requests.append((dataset, num_requests))
            
        requests.sort(key = lambda x: x[0].attr['request_weight'], reverse = True)

        datasets_to_request = []

        # [(d1, n1), (d2, n2), ...] -> [d1, d2, .., d1, ..] (d1 repeats n1 times)
        while True:
            added_request = False
            for ir in xrange(len(requests)):
                dataset, num_requests = requests[ir]
                if num_requests == 0:
                    continue

                datasets_to_request.append(dataset)
                requests[ir] = (dataset, num_requests - 1)
                added_request = True

            if not added_request:
                break
        
        return datasets_to_request

    def save_record(self, run_number, history, copy_list): # override
        history.save_dataset_popularity(run_number, self._datasets)
