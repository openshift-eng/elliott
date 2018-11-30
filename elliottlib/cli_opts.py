CLI_OPTS = {
    'data_path': {
        'env': 'ELLIOTT_DATA_PATH',
        'help': 'Git URL or File Path to build data'
    },
    'group': {
        'env': 'ELLIOTT_GROUP',
        'help': 'Sub-group directory or branch to pull build data'
    },
    'working_dir': {
        'env': 'ELLIOTT_WORKING_DIR',
        'help': 'Persistent working directory to use'
    },
}

CLI_ENV_VARS = {k: v['env'] for (k, v) in CLI_OPTS.iteritems()}

CLI_CONFIG_TEMPLATE = '\n'.join(['#{}\n{}:\n'.format(v['help'], k) for (k, v) in CLI_OPTS.iteritems()])