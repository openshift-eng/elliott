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


def id_convert(ids):
    # this function convert string list param --id "1" --id "2" --id "3,4,5"
    # to int list [1,2,3,4,5]
    id_str = []
    for id in ids:
        # id = "1234,42345,1234,"
        if ',' in id:
            for k in [c.strip() for c in id.split(',')]:
                id_str.append(k)
        # id = 123  no ','
        else:
            id_str.append(id)
    return [int(s) for s in id_str]
