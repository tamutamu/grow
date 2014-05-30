from .destinations.amazon_s3 import *
from .destinations.local import *
from .destinations.google_cloud_storage import *
from .destinations.google_cloud_storage_from_app_engine import *
from .destinations.zip_file import *
from .destinations.scp import *


class Deployment(object):

  @classmethod
  def get(cls, kind, *args, **kwargs):
    if kind == 'gcs':
      return GoogleCloudStorageDeployment(*args, **kwargs)
    elif kind == 's3':
      return AmazonS3Deployment(*args, **kwargs)
    elif kind == 'local':
      return LocalDeployment(*args, **kwargs)
    elif kind == 'scp':
      return ScpDeployment(*args, **kwargs)
    raise ValueError('No configuration exists for "{}".'.format(kind))
