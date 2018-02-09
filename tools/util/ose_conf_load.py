import subprocess
import sys
import json
import yaml
import os
import tempfile
import urllib
import dockerfile_parse

cur_dir = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))


def resolve_none(val):
    return val if val != 'None' else None


def proc_image_type(val):
    result = resolve_none(val)
    if not result:
        result = 'rpms'
    return result


def proc_image_from(val):
    vals = val.split(' ')
    vals = [resolve_none(v) for v in vals]
    return {
        'from': vals[0],
        'dependency': vals[1],
    }


def proc_git_compare(val):
    vals = val.split(' ')
    vals = [resolve_none(v) for v in vals]
    return {
        'repo': vals[0],
        'path': vals[1],
        'dockerfile': vals[2],
        'style': vals[3],
    }


def proc_image_name(val):
    return resolve_none(val)


def proc_image_tags(val):
    return [resolve_none(v) for v in val.split(' ')]


sub_dicts = {
    'dict_image_type': proc_image_type,
    'dict_image_from': proc_image_from,
    'dict_git_compare': proc_git_compare,
    'dict_image_name': proc_image_name,
    'dict_image_tags': proc_image_tags,
}

out_dir = sys.argv[1]
branch = sys.argv[2]
version = branch.split('-')[2]
ose_conf_path = sys.argv[3]
group = 'base' if len(sys.argv) < 5 else sys.argv[4]

data = subprocess.check_output([os.path.join(cur_dir, 'ose_conf_load.sh'), version, ose_conf_path])
data = json.loads(data)

ose_conf = {}

for d in sub_dicts.keys():
    base = d.replace('dict_', '')
    for name, val in data[d].items():
        if name not in ose_conf:
            ose_conf[name] = {}
            ose_conf[name]['image_type'] = 'rpms'
        ose_conf[name][base] = sub_dicts[d](val)

ose_images_path = ose_conf_path.replace('ose.conf', 'ose_images.sh')
group_images = subprocess.check_output(
    (ose_images_path + ' test --branch ' +
     branch + ' --group base').split(' '))
group_images = group_images.replace('\t', ' ')
print(group_images)
group_images = [img.split(' ')[1] for img in group_images.splitlines()]

member_images = list(ose_conf.keys())

dockerfile_base_url = 'http://pkgs.devel.redhat.com/cgit/{}/{}/plain/Dockerfile?h={}'
tmp_dir = tempfile.mkdtemp()

dockerfiles = {}
print('Fetching Dockerfiles')
for img in group_images:
    img_type = ose_conf[img]['image_type']
    df = os.path.join(tmp_dir, img + '.Dockerfile')
    dockerfiles[img] = df
    url = dockerfile_base_url.format(img_type, img, branch)
    print('Downloading {} to\n{}\n'.format(url, df))
    urllib.urlretrieve(url, df)

req_labels = [
    'vendor',
    'License',
    'architecture',
    'io.k8s.display-name',
    'io.k8s.description',
    'io.openshift.tags'
]
for img, df in dockerfiles.items():
    print(df)
    dfp = dockerfile_parse.DockerfileParser(path=df)
    # print(ose_conf[img])
    ose = ose_conf[img]
    config = {
        'repo': {
            'type': ose['image_type']
        },
        'name': ose['image_name'] or dfp.labels['name'],
        'content': {
            'source': {}
        },
        'from': {},
        'labels': {
            'vendor': 'Red Hat',
            'License': 'GPLv2+'
        },
        'owners': []
    }

    if ose['image_from']['dependency'] in group_images:
        config['from'] = {'member': ose['image_from']['dependency']}
    elif (ose['image_from']['dependency'] is None and
          ose['image_from']['from'] == 'rhel' and
          dfp.baseimage.startswith('rhel')):
            config['from']['stream'] = 'rhel'
    elif dfp.baseimage.startswith('rhel7'):
        config['from']['stream'] = 'rhel'
    else:
        config['from']['image'] = dfp.baseimage

    if ose['git_compare'].get('path', None):
        path_split = ose['git_compare']['path'].split('/')
        config['content']['source']['alias'] = path_split[0]
        config['content']['source']['path'] = '/'.join(path_split[1:])
    else:
        del config['content']

    lbls = config['labels']
    for l in req_labels:
        if l in dfp.labels:
            lbls[l] = dfp.labels[l]

    if 'maintainer' in dfp.labels:
        config['owners'].append(dfp.labels['maintainer'].split(' ')[-1].strip('<>'))
    else:
        with open(df, 'r') as dff:
            lines = dff.readlines()
            for line in lines:
                if line.strip().startswith('MAINTAINER'):
                    config['owners'].append(line.strip().split(' ')[-1].strip('<>'))
                    break

    cfg_dir = os.path.join(out_dir, img)
    if not os.path.isdir(cfg_dir):
        os.mkdir(cfg_dir)
    cfg_yml = os.path.join(cfg_dir, 'config.yml')

    with open(cfg_yml, 'w') as cfg_file:
        print('Writing ' + cfg_yml)
        yaml.safe_dump(config, cfg_file, indent=2, default_flow_style=False)
