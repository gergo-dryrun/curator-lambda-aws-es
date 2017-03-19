from __future__ import print_function
import os

from aws_requests_auth.aws_auth import AWSRequestsAuth
import boto3
import certifi
import curator
from curator.exceptions import NoIndices
from elasticsearch import Elasticsearch, RequestsHttpConnection
import yaml


def monkeypatch_method(cls):
    def decorator(func):
        setattr(cls, func.__name__, func)
        return func
    return decorator

# Monkey patching #https://github.com/elastic/curator/issues/880
# PR https://github.com/Talend/curator/pull/1 merged but not in pypi
@monkeypatch_method(curator.IndexList)
def _get_metadata(self):
    from curator.utils import *
    """
    Populate `index_info` with index `size_in_bytes` and doc count
    information for each index.
    """
    self.loggit.debug('Getting index metadata')
    self.empty_list_check()
    index_lists = chunk_index_list(self.indices)
    for l in index_lists:
        working_list = (
            self.client.cluster.state(
                index=to_csv(l), metric='metadata'
            )['metadata']['indices']
        )
        if working_list:
            for index in list(working_list.keys()):
                s = self.index_info[index]
                wl = working_list[index]
                if 'settings' not in wl:
                    # We can try to get the same info from index/_settings.
                    # To work around https://github.com/elastic/curator/issues/880
                    alt_wl = self.client.indices.get(index, feature='_settings')[index]
                    wl['settings'] = alt_wl['settings']

                if 'creation_date' not in wl['settings']['index']:
                    self.loggit.warn(
                        'Index: {0} has no "creation_date"! This implies '
                        'that the index predates Elasticsearch v1.4. For '
                        'safety, this index will be removed from the '
                        'actionable list.'.format(index)
                    )
                    self.__not_actionable(index)
                else:
                    s['age']['creation_date'] = (
                        fix_epoch(wl['settings']['index']['creation_date'])
                    )
                s['number_of_replicas'] = (
                    wl['settings']['index']['number_of_replicas']
                )
                s['number_of_shards'] = (
                    wl['settings']['index']['number_of_shards']
                )
                s['state'] = wl['state']
                if 'routing' in wl['settings']['index']:
                    s['routing'] = wl['settings']['index']['routing']


def run_curator(cluster_config):

    cluster_endpoint = 'https://%s' % cluster_config['endpoint']

    auth = AWSRequestsAuth(aws_access_key=os.environ['AWS_ACCESS_KEY_ID'],
                           aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
                           aws_host=cluster_config['endpoint'],
                           aws_region=os.environ['AWS_DEFAULT_REGION'],
                           aws_service='es',
                           aws_token=os.environ['AWS_SESSION_TOKEN'])

    es = Elasticsearch(cluster_endpoint,
                       connection_class=RequestsHttpConnection,
                       http_auth=auth,
                       use_ssl=True,
                       verify_certs=True,
                       ca_certs=certifi.where())

    deleted_indices = []
    for index in cluster_config['indices']:
        index_prefix = index['prefix']
        retention = index['days']
        print('Checking "%s" indices on %s cluster.' %
              (index_prefix, cluster_config['name']))

        index_list = curator.IndexList(es)
        try:
            index_list.filter_by_regex(kind='prefix', value=index_prefix)
            index_list.filter_by_age(source='name', direction='older',
                                     timestring='%Y.%m.%d', unit='days',
                                     unit_count=retention)
            curator.DeleteIndices(index_list).do_action()
        except NoIndices:
            pass
        deleted_indices += index_list.working_list()

    return deleted_indices


def download_config():
    config_location = os.environ['CONFIG_LOCATION']
    bucket_name, config_path = config_location.split('/', 1)
    s3 = boto3.resource('s3')
    object = s3.Object(bucket_name, config_path)
    config = yaml.load(object.get()['Body'].read())
    return config


def lambda_handler(event, context):

    config = download_config()
    deleted_indices = {}
    for cluster_config in config:
        cluster_name = cluster_config['name']
        deleted = run_curator(cluster_config)
        deleted_indices[cluster_name] = deleted

    lambda_response = {'deleted': deleted_indices}
    print(lambda_response)
    return lambda_response


if __name__ == '__main__':
    lambda_handler(None, None)

