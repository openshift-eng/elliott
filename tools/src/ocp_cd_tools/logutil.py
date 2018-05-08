import logging


class EntityLoggingAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return '[%s] %s' % (self.extra['entity'], msg), kwargs


def getLogger(module_name=None):
    """
    Returns a logger appropriate for use in the ocp_cd_tools
    module. Modules should request a logger using their __name__
    """
    logger_name = 'ocp_cd_tools'

    if module_name:
        logger_name = '{}.{}'.format(logger_name, module_name)

    return logging.getLogger(logger_name)
