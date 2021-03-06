class DatasetInfoSource(object):
    """
    Interface specs for probe to the dataset information source.
    """

    def __init__(self, config):
        if hasattr(config, 'include'):
            if type(config.include) is list:
                self.include = list(config.include)
            else:
                self.include = [config.include]
        else:
            self.include = None

        if hasattr(config, 'exclude'):
            if type(config.exclude) is list:
                self.exclude = list(config.exclude)
            else:
                self.exclude = [config.exclude]
        else:
            self.exclude = None

    def get_dataset_names(self, include = ['*'], exclude = []):
        """
        Return a list of dataset names from the include and exclude patterns.
        
        @param include  List of fnmatch patterns of the dataset names to be included.
        @param exclude  List of fnmatch patterns to exclude from the included list.
        """
        raise NotImplementedError('get_dataset_names')

    def get_updated_datasets(self, updated_since):
        """
        Get a list of updated Datasets-Blocks-Files with full information.
        @param updated_since  Unix timestamp
        @return  List of datasets
        """
        raise NotImplementedError('get_updated_datasets')

    def get_dataset(self, name, with_files = False):
        """
        Get a linked structure of Dataset-Blocks-Files with full information.
        @param name  Name of dataset
        @return  Dataset with full list of Blocks and Files
        """
        raise NotImplementedError('get_dataset')

    def get_block(self, name, dataset = None, with_files = False):
        """
        Get a linked set of Blocks-Files with full information.
        @param name     Name of block
        @param dataset  If not None, link the block against this dataset.
        @return  Block with full list of Files
        """
        raise NotImplementedError('get_block')

    def get_file(self, name, block = None):
        """
        Get a File object.
        @param name  Name of file
        @param block If not None, link the file against this block.
        @return  File
        """
        raise NotImplementedError('get_file')

    def get_files(self, dataset_or_block):
        """
        Get a set of File objects. Files will not be linked from the block.
        @param dataset_or_block  Dataset or Block object
        @return set of Files
        """
        raise NotImplementedError('get_files')
