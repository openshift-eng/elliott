from .metadata import Metadata


class RPMMetadata(Metadata):
    def __init__(self, runtime, data_obj):
        super(RPMMetadata, self).__init__('rpm', runtime, data_obj)
        self.rpm_name = self.config.name
