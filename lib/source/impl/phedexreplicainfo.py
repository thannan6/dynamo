import logging

from dynamo.source.replicainfo import ReplicaInfoSource
from dynamo.utils.interface.phedex import PhEDEx
from dynamo.dataformat import Group, Site, Dataset, Block, DatasetReplica, BlockReplica

LOG = logging.getLogger(__name__)

class PhEDExReplicaInfoSource(ReplicaInfoSource):
    """ReplicaInfoSource using PhEDEx."""

    def __init__(self, config):
        ReplicaInfoSource.__init__(self, config)

        self._phedex = PhEDEx(config.phedex)

    def replica_exists_at_site(self, site, item): #override
        options = ['node=' + site.name]

        if type(item) == Dataset:
            options += ['dataset=' + item.name, 'show_dataset=y']
        elif type(item) == DatasetReplica:
            options += ['dataset=' + item.dataset.name, 'show_dataset=y']
        elif type(item) == Block:
            options += ['block=' + item.full_name()]
        elif type(item) == BlockReplica:
            options += ['block=' + item.block.full_name()]
        else:
            raise RuntimeError('Invalid input passed: ' + repr(item))
        
        source = self._phedex.make_request('blockreplicas', options)

        return len(source) != 0

    def get_replicas(self, site = None, dataset = None, block = None): #override
        options = []
        if site is not None:
            options.append('node=' + site)
        if dataset is not None:
            options.append('dataset=' + dataset)
        if block is not None:
            options.append('block=' + block)

        LOG.info('get_replicas(' + ','.join(options) + ')  Fetching the list of replicas from PhEDEx')

        if len(options) == 0:
            return []
        
        result = self._phedex.make_request('blockreplicas', ['show_dataset=y'] + options)

        return PhEDExReplicaInfoSource.make_block_replicas(result, PhEDExReplicaInfoSource.maker_blockreplicas)

    def get_updated_replicas(self, updated_since): #override
        LOG.info('get_updated_replicas(%d)  Fetching the list of replicas from PhEDEx', updated_since)

        result = self._phedex.make_request('blockreplicas', ['show_dataset=y', 'update_since=%d' % updated_since])
        
        return PhEDExReplicaInfoSource.make_block_replicas(result, PhEDExReplicaInfoSource.maker_blockreplicas)

    def get_deleted_replicas(self, deleted_since): #override
        LOG.info('get_deleted_replicas(%d)  Fetching the list of replicas from PhEDEx', deleted_since)

        result = self._phedex.make_request('deletions', ['complete_since=%d' % deleted_since])

        return PhEDExReplicaInfoSource.make_block_replicas(result, PhEDExReplicaInfoSource.maker_deletions)

    @staticmethod
    def make_block_replicas(dataset_entries, replica_maker):
        """Return a list of block replicas linked to Dataset, Block, Site, and Group"""

        block_replicas = []

        for dataset_entry in dataset_entries:
            dataset = Dataset(
                dataset_entry['name']
            )
            
            for block_entry in dataset_entry['block']:
                name = block_entry['name']
                try:
                    block_name = Block.to_internal_name(name[name.find('#') + 1:])
                except ValueError: # invalid name
                    continue

                block = Block(
                    block_name,
                    dataset,
                    block_entry['bytes']
                )

                block_replicas.extend(replica_maker(block, block_entry))

        return block_replicas

    @staticmethod
    def maker_blockreplicas(block, block_entry):
        replicas = []

        for replica_entry in block_entry['replica']:
            block_replica = BlockReplica(
                block,
                Site(replica_entry['node']),
                Group(replica_entry['group']),
                is_complete = (replica_entry['bytes'] == block.size),
                is_custodial = (replica_entry['custodial'] == 'y'),
                size = replica_entry['bytes'],
                last_update = int(replica_entry['time_update'])
            )

            replicas.append(block_replica)

        return replicas

    @staticmethod
    def maker_deletions(block, block_entry):
        replicas = []

        for deletion_entry in block_entry['deletion']:
            block_replica = BlockReplica(block, Site(deletion_entry['node']), Group.null_group)

            replicas.append(block_replica)

        return replicas
