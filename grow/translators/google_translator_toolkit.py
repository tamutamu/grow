from . import base
from googleapiclient import discovery
from googleapiclient import errors
from grow.common import oauth
from grow.common import utils
import datetime
import base64
import httplib2
import json
import logging
import urllib


EDIT_URL_FORMAT = 'https://translate.google.com/toolkit/workbench?did={}'
GTT_DOCUMENTS_BASE_URL = 'https://www.googleapis.com/gte/v1/documents'
OAUTH_SCOPE = 'https://www.googleapis.com/auth/gte'
STORAGE_KEY = 'Grow SDK - Google Translator Toolkit'


class AccessLevel(object):
    ADMIN = 'ADMIN'
    READ_AND_COMMENT = 'READ_AND_COMMENT'
    READ_AND_WRITE = 'READ_AND_WRITE'
    READ_ONLY = 'READ_ONLY'


class ChangeType(object):
    MODIFY = 'MODIFY'
    ADD = 'ADD'


def raise_service_error(http_error, locale=None, ident=None):
    message = 'HttpError {} for {} returned "{}"'.format(
        http_error.resp.status, http_error.uri,
        http_error._get_reason().strip())
    raise base.TranslatorServiceError(message=message, locale=locale, ident=ident)


class Gtt(object):

    def __init__(self):
        self.service = discovery.build('gte', 'v1', http=self.http)

    @property
    def http(self):
        credentials = oauth.get_credentials(
            scope=OAUTH_SCOPE, storage_key=STORAGE_KEY)
        http = httplib2.Http(ca_certs=utils.get_cacerts_path())
        http = credentials.authorize(http)
        return http

    def get_document(self, document_id):
        return self.service.documents().get(documentId=document_id).execute()

    def get_user_from_acl(self, document_id, email):
        document = self.get_document(document_id)
        for user in document['gttAcl']:
            if user.get('emailId') == email:
                return user

    def update_acl(self, document_id, email, access_level, can_reshare=True,
                   update=False):
        acl_change_type = ChangeType.MODIFY if update else ChangeType.ADD
        body = {
            'gttAclChange': {
                [
                    {
                        'accessLevel': access_level,
                        'canReshare': can_reshare,
                        'emailId': email,
                        'type': acl_change_type,
                    }
                ]
            }
        }
        return self.service.documents().update(
            documentId=document_id, body=body).execute()

    def share_document(self, document_id, email,
                       access_level=AccessLevel.READ_AND_WRITE):
        in_acl = self.get_user_from_acl(document_id, email)
        update = True if in_acl else False
        return self.update_acl(document_id, email,
                               access_level=access_level, update=update)

    def insert_document(self, name, content, source_lang, lang, mimetype,
                        acl=None, tm_ids=None, glossary_ids=None):
        content = base64.urlsafe_b64encode(content)
        doc = {
            'displayName': name,
            'gttAcl': acl,
            'language': lang,
            'mimetype': mimetype,
            'sourceDocBytes': content,
            'sourceLang': source_lang,
        }
        if acl:
            doc['gttAcl'] = acl
        if tm_ids:
            doc['tmIds'] = tm_ids
        if glossary_ids:
            doc['glossaryIds'] = glossary_ids
        try:
            return self.service.documents().insert(body=doc).execute()
        except errors.HttpError as resp:
            raise_service_error(locale=lang, http_error=resp)

    def download_document(self, document_id):
        params = {
            'alt': 'media',
            'downloadContent': True,
        }
        url = '{}/{}?{}'.format(
            GTT_DOCUMENTS_BASE_URL,
            urllib.quote(document_id), urllib.urlencode(params))
        response, content = self.http.request(url)
        try:
            if response.status >= 400:
                raise errors.HttpError(response, content, uri=url)
        except errors.HttpError as resp:
            raise_service_error(ident=document_id, http_error=resp)
        return content


class GoogleTranslatorToolkitTranslator(base.Translator):
    KIND = 'google_translator_toolkit'
    has_immutable_translation_resources = True

    def _normalize_source_lang(self, source_lang):
        if source_lang is None:
            return 'en'
        source_lang = str(source_lang)
        source_lang = source_lang.lower()
        if source_lang == 'en_us':
            return 'en'
        return source_lang

    def _download_content(self, stat):
        gtt = Gtt()
        content = gtt.download_document(stat.ident)
        resp = gtt.get_document(stat.ident)
        stat = self._create_stat_from_gtt_response(resp, downloaded=True)
        return stat, content

    def _create_stat_from_gtt_response(self, resp, downloaded=False):
        edit_url = EDIT_URL_FORMAT.format(resp['id'])
        lang = resp['language']
        source_lang = resp['sourceLang']
        stat = base.TranslatorStat(
            edit_url=edit_url,
            lang=lang,
            num_words=resp['numWords'],
            num_words_translated=resp['numWordsTranslated'],
            source_lang=source_lang,
            service=GoogleTranslatorToolkitTranslator.KIND,
            ident=resp['id'])
        if downloaded:
            stat.downloaded = datetime.datetime.now()
        else:
            stat.uploaded = datetime.datetime.now()
        return stat

    def _upload_catalog(self, catalog, source_lang):
        gtt = Gtt()
        project_title = self.project_title
        name = '{} ({})'.format(project_title, str(catalog.locale))
        source_lang = self._normalize_source_lang(source_lang)
        glossary_ids = None
        acl = None
        tm_ids = self.config.get('tm_ids')
        glossary_ids = self.config.get('glossary_ids')
        if 'acl' in self.config:
            acl = []
            for item in self.config['acl']:
                access_level = item.get('access_level',
                                        AccessLevel.READ_AND_WRITE)
                acl.append({
                    'emailId': item['email'],
                    'accessLevel': access_level
                })
        lang = str(catalog.locale)
        resp = gtt.insert_document(
            name=name,
            content=catalog.content,
            source_lang=str(source_lang),
            lang=lang,
            tm_ids=tm_ids,
            glossary_ids=glossary_ids,
            mimetype='text/x-gettext-translation',
            acl=acl)
        return self._create_stat_from_gtt_response(resp)
