# Copyright Cloudinary
import json
import base64
import sys
import email.utils
import socket
import urllib3
import cloudinary
from cloudinary.compat import urllib2, urlencode, to_string, to_bytes, PY3
from cloudinary import utils
from urllib3.exceptions import HTTPError


class Error(Exception): pass
class NotFound(Error): pass
class NotAllowed(Error): pass
class AlreadyExists(Error): pass
class RateLimited(Error): pass
class BadRequest(Error): pass
class GeneralError(Error): pass
class AuthorizationRequired(Error): pass

EXCEPTION_CODES = {
    400: BadRequest,
    401: AuthorizationRequired,
    403: NotAllowed,
    404: NotFound,
    409: AlreadyExists,
    420: RateLimited,
    500: GeneralError
}

class Response(dict):
    def __init__(self, result, response):
        self.update(result)
        self.rate_limit_allowed = int(response.headers["x-featureratelimit-limit"])
        self.rate_limit_reset_at = email.utils.parsedate(response.headers["x-featureratelimit-reset"])
        self.rate_limit_remaining = int(response.headers["x-featureratelimit-remaining"])

def ping(**options):
    return call_api("get", ["ping"], {}, **options)

def usage(**options):
    return call_api("get", ["usage"], {}, **options)

def resource_types(**options):
    return call_api("get", ["resources"], {}, **options)

def resources(**options):
    resource_type = options.pop("resource_type", "image")
    type = options.pop("type", None)
    uri = ["resources", resource_type]
    if type: uri.append(type)
    return call_api("get", uri, only(options, "next_cursor", "max_results", "prefix", "tags", "context", "moderations", "direction", "start_at"), **options)

def resources_by_tag(tag, **options):
    resource_type = options.pop("resource_type", "image")
    uri = ["resources", resource_type, "tags", tag]
    return call_api("get", uri, only(options, "next_cursor", "max_results", "tags", "context", "moderations", "direction"), **options)

def resources_by_moderation(kind, status, **options):
    resource_type = options.pop("resource_type", "image")
    uri = ["resources", resource_type, "moderations", kind, status]
    return call_api("get", uri, only(options, "next_cursor", "max_results", "tags", "context", "moderations", "direction"), **options)

def resources_by_ids(public_ids, **options):
    resource_type = options.pop("resource_type", "image")
    type = options.pop("type", "upload")
    uri = ["resources", resource_type, type]
    params = [("public_ids[]", public_id) for public_id in public_ids]
    optional = list(only(options, "tags", "moderations", "context").items())
    return call_api("get", uri, params + optional, **options)

def resource(public_id, **options):
    resource_type = options.pop("resource_type", "image")
    type = options.pop("type", "upload")
    uri = ["resources", resource_type, type, public_id]
    return call_api("get", uri, only(options, "exif", "faces", "colors", "image_metadata", "pages", "phash", "coordinates", "max_results"), **options)

def update(public_id, **options):
    resource_type = options.pop("resource_type", "image")
    type = options.pop("type", "upload")
    uri = ["resources", resource_type, type, public_id]
    upload_options = only(options, "moderation_status", "raw_convert", "ocr", "categorization", "detection", "similarity_search", "background_removal")
    if "tags" in options: upload_options["tags"] = ",".join(utils.build_array(options["tags"]))
    if "face_coordinates" in options: upload_options["face_coordinates"] = utils.encode_double_array(options.get("face_coordinates")) 
    if "custom_coordinates" in options: upload_options["custom_coordinates"] = utils.encode_double_array(options.get("custom_coordinates")) 
    if "context" in options: upload_options["context"] = utils.encode_dict(options.get("context")) 
    if "auto_tagging" in options: upload_options["auto_tagging"] = float(options.get("auto_tagging"))
    return call_api("post", uri, upload_options, **options)

def delete_resources(public_ids, **options):
    resource_type = options.pop("resource_type", "image")
    type = options.pop("type", "upload")
    uri = ["resources", resource_type, type]
    params = [("public_ids[]", public_id) for public_id in public_ids]
    optional = list(only(options, "keep_original", "next_cursor", "invalidate").items())
    return call_api("delete", uri, params + optional, **options)

def delete_resources_by_prefix(prefix, **options):
    resource_type = options.pop("resource_type", "image")
    type = options.pop("type", "upload")
    uri = ["resources", resource_type, type]
    return call_api("delete", uri, dict(only(options, "keep_original", "next_cursor", "invalidate"), prefix=prefix), **options)

def delete_all_resources(**options):
    resource_type = options.pop("resource_type", "image")
    type = options.pop("type", "upload")
    uri = ["resources", resource_type, type]
    optional = list(only(options, "keep_original", "next_cursor").items())
    return call_api("delete", uri, dict(only(options, "keep_original", "next_cursor", "invalidate"), all=True), **options)

def delete_resources_by_tag(tag, **options):
    resource_type = options.pop("resource_type", "image")
    uri = ["resources", resource_type, "tags", tag]
    return call_api("delete", uri, only(options, "keep_original", "next_cursor", "invalidate"), **options)

def delete_derived_resources(derived_resource_ids, **options):
    uri = ["derived_resources"]
    params = [("derived_resource_ids[]", derived_resource_id) for derived_resource_id in derived_resource_ids]

    return call_api("delete", uri, params, **options)

def tags(**options):
    resource_type = options.pop("resource_type", "image")
    uri = ["tags", resource_type]
    return call_api("get", uri, only(options, "next_cursor", "max_results", "prefix"), **options)

def transformations(**options):
    uri = ["transformations"]
    return call_api("get", uri, only(options, "next_cursor", "max_results"), **options)

def transformation(transformation, **options):
    uri = ["transformations", transformation_string(transformation)]
    return call_api("get", uri, only(options, "next_cursor", "max_results"), **options)

def delete_transformation(transformation, **options):
    uri = ["transformations", transformation_string(transformation)]
    return call_api("delete", uri, {}, **options)

# updates - currently only supported update is the "allowed_for_strict" boolean flag and unsafe_update
def update_transformation(transformation, **options):
    uri = ["transformations", transformation_string(transformation)]
    updates = only(options, "allowed_for_strict")
    if "unsafe_update" in options:
      updates["unsafe_update"] = transformation_string(options.get("unsafe_update")) 
    if len(updates) == 0: raise Exception("No updates given")

    return call_api("put", uri, updates, **options)

def create_transformation(name, definition, **options):
    uri = ["transformations", name]
    return call_api("post", uri, {"transformation": transformation_string(definition)}, **options)

def upload_presets(**options):
    uri = ["upload_presets"]
    return call_api("get", uri, only(options, "next_cursor", "max_results"), **options)

def upload_preset(name, **options):
    uri = ["upload_presets", name]
    return call_api("get", uri, only(options, "max_results"), **options)

def delete_upload_preset(name, **options):
    uri = ["upload_presets", name]
    return call_api("delete", uri, {}, **options)

def update_upload_preset(name, **options):
    uri = ["upload_presets", name]
    params = utils.build_upload_params(**options)
    params = utils.cleanup_params(params)
    params.update(only(options, "unsigned", "disallow_public_id"))
    return call_api("put", uri, params, **options)

def create_upload_preset(**options):
    uri = ["upload_presets"]
    params = utils.build_upload_params(**options)
    params = utils.cleanup_params(params)
    params.update(only(options, "unsigned", "disallow_public_id", "name"))
    return call_api("post", uri, params, **options)

def root_folders(**options):
    return call_api("get", ["folders"], {}, **options)

def subfolders(of_folder_path, **options):
    return call_api("get", ["folders", of_folder_path], {}, **options)

def restore(public_ids, **options):
    resource_type = options.pop("resource_type", "image")
    type = options.pop("type", "upload")
    uri = ["resources", resource_type, type, "restore"]
    params = [("public_ids[]", public_id) for public_id in public_ids]
    return call_api("post", uri, params, **options)

def upload_mappings(**options):
    uri = ["upload_mappings"]
    return call_api("get", uri, only(options, "next_cursor", "max_results"), **options)
  
def upload_mapping(name, **options):
    uri = ["upload_mappings"]    
    params = dict(folder = name)
    return call_api("get", uri, params, **options)
  
def delete_upload_mapping(name, **options):
    uri = ["upload_mappings"]
    params = dict(folder = name)
    return call_api("delete", uri, params, **options)
    
def update_upload_mapping(name, **options):
    uri = ["upload_mappings"]
    params = dict(folder = name)
    params.update(only(options, "template"))
    return call_api("put", uri, params, **options)
  
def create_upload_mapping(name, **options):
    uri = ["upload_mappings"]
    params = dict(folder = name)
    params.update(only(options, "template"))
    return call_api("post", uri, params, **options)

def call_api(method, uri, params, **options):
    prefix = options.pop("upload_prefix", cloudinary.config().upload_prefix) or "https://api.cloudinary.com"
    cloud_name = options.pop("cloud_name", cloudinary.config().cloud_name)
    if not cloud_name: raise Exception("Must supply cloud_name")
    api_key = options.pop("api_key", cloudinary.config().api_key)
    if not api_key: raise Exception("Must supply api_key")
    api_secret = options.pop("api_secret", cloudinary.config().api_secret)
    if not cloud_name: raise Exception("Must supply api_secret")
    exception_class = None
    data = to_bytes(urlencode(params))
    api_url = "/".join([prefix, "v1_1", cloud_name] + uri)
    request = urllib2.Request(api_url, data)
    # Add authentication
    byte_value = to_bytes('%s:%s' % (api_key, api_secret))
    encoded_value = base64.encodebytes(byte_value) if PY3 else base64.encodestring(byte_value)
    base64string = to_string(encoded_value).replace('\n', '')
    headers = urllib3.make_headers(basic_auth="{0}:{1}".format(api_key, api_secret), user_agent=cloudinary.get_user_agent())
    # headers = {
    #     "Authorization": "Basic %s" % base64string,
    #     "User-Agent": cloudinary.get_user_agent()
    # }

    kw = {}
    if 'timeout' in options:
        kw['timeout'] = options['timeout']
    try:
        http = urllib3.PoolManager()
        response = http.request(method.upper(), api_url, params, headers, **kw)
        body = response.data
    except HTTPError as e:
        raise GeneralError("Unexpected error {0}", e.message)
    except socket.error as e:
        raise GeneralError("Socket Error: %s" % (str(e)))

    try:
        result = json.loads(body.decode('utf-8'))
    except Exception as e:
        # Error is parsing json
        raise GeneralError("Error parsing server response (%d) - %s. Got - %s" % (response.status, body, e))

    if "error" in result:
        exception_class = EXCEPTION_CODES.get(response.status) or Exception
        exception_class = exception_class 
        raise exception_class("Error {0} - {1}".format(response.status, result["error"]["message"]))

    return Response(result, response)

def only(hash, *keys):
    result = {}
    for key in keys:
        if key in hash: result[key] = hash[key]
    return result

def transformation_string(transformation):
    return transformation if isinstance(transformation, str) else cloudinary.utils.generate_transformation_string(**transformation)[0]

