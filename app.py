from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_restplus import Api, Resource, fields
from datetime import datetime
from elasticsearch import Elasticsearch
import mysql.connector
import pika
import redis
from datetime import datetime, timedelta
import configparser
import json
import io
import os




app = Flask(__name__)
CORS(app)
api = Api(app, version='1.0', title='PIOLINK Elasticsearch API',
    description='PIOLINK Elasticsearch API for dashboards',
)

config = configparser.ConfigParser()
config.read('config.ini')

es = Elasticsearch(config["ElasticSearch"]["url"], basic_auth=(config["ElasticSearch"]["uid"], config["ElasticSearch"]["pwd"]))

@api.route('/es_count')
class EsRoot(Resource):
    def get(self):
        resp = es.count()
        return resp['count']

@api.route('/es')
class EsRoot(Resource):
    def get(self):
        resp = es.search(index="*", query={"match_all": {}},size=1000, sort= [{"reg_date":{"order": "desc"}}])
        return jsonify(resp['hits']['hits'])

@api.route('/es/<id>')
@api.doc(params={'id': 'An ID'})
class EsResource(Resource):

    def get(self, id):
       resp = es.search(index="*", query={"match_all": {}},size=100, from_=id)
       return jsonify(resp['hits']['hits'])


    @api.response(403, 'Not Authorized')
    def post(self, id):
        api.abort(403)

# ===============DashBoard API=================================

c_mysql_ip = config["MySQL"]["mysql_ip"]
c_mysql_id = config["MySQL"]["mysql_id"]
c_mysql_pw = config["MySQL"]["mysql_pw"]
c_redis_ip = config["MySQL"]["redis_ip"]
c_redis_pw = config["MySQL"]["redis_pw"]
c_sitename = config["MySQL"]["sitename"]

@api.route('/monitoring/count_info')
class ReportCountInfo(Resource):

    def get(self):
        m_start_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
        m_end_date = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

        m_es_filter_type_url = {'term': {'type.keyword': 'url'}}
        m_es_filter_type_file = {'term': {'type.keyword': 'file'}}
        m_es_filter_gte = {'range': {'reg_date': {'gte': m_start_date}}}
        m_es_filter_lte = {'range': {'reg_date': {'lte': m_end_date}}}

        m_crawler_url_count = 0
        m_urlhunter_url_count = 0
        m_crawler_file_count = 0

        m_json = {}

        try:
            resp_cnt = es.count(index="analysis*", query={
                'bool': {
                    'filter': [
                        m_es_filter_type_url,
                        m_es_filter_gte,
                        m_es_filter_lte
                    ]
                }
            })
            m_crawler_url_count = resp_cnt['count']

            resp_cnt = es.count(index="analysis*", query={
                'bool': {
                    'filter': [
                        m_es_filter_type_file,
                        m_es_filter_gte,
                        m_es_filter_lte
                    ]
                }
            })
            m_crawler_file_count = resp_cnt['count']

            # (1) MYSQL ??????
            connection = mysql.connector.connect(host=c_mysql_ip, database='urlhunter_flask', user=c_mysql_id, password=c_mysql_pw)

            with connection:
                with connection.cursor(buffered=True) as cur:
                    cur.execute('SELECT count(*) FROM site_contents')
                    url_hunter_result = cur.fetchone()
            connection.close()
            m_urlhunter_url_count = url_hunter_result[0]

            m_redis = redis.Redis(host=c_redis_ip, port=6379, password=c_redis_pw, charset="utf-8", decode_responses=True)

            m_analysis_waiting_data_json = json.loads(m_redis.get('analysis_waiting_data'))
            # {
            #     "file_crawling_queue_waiting_count": 20778,
            #     "file_crawling_queue_consuming_count": 2,
            #     "url_crawling_queue_waiting_count": 434257,
            #     "url_crawling_queue_consuming_count": 12,
            #     "url_hunter_queue_waiting_count": 0,
            #     "url_hunter_queue_consuming_count": 12
            # }


            m_json['total_url_count'] = m_crawler_url_count + \
                                        m_urlhunter_url_count + \
                                        int(m_analysis_waiting_data_json['url_crawling_queue_waiting_count']) + \
                                        int(m_analysis_waiting_data_json['url_crawling_queue_consuming_count']) + \
                                        int(m_analysis_waiting_data_json['url_hunter_queue_waiting_count']) + \
                                        int(m_analysis_waiting_data_json['url_hunter_queue_consuming_count'])

            m_json['total_file_count'] = m_crawler_file_count + \
                                        int(m_analysis_waiting_data_json['file_crawling_queue_waiting_count']) + \
                                        int(m_analysis_waiting_data_json['file_crawling_queue_consuming_count'])

            m_json['crawler_url_count'] = m_crawler_url_count
            m_json['urlhunter_url_count'] = m_urlhunter_url_count
            m_json['crawler_file_count'] = m_crawler_file_count

            m_json['analysis_waiting_url_count'] = int(m_analysis_waiting_data_json['url_crawling_queue_waiting_count']) + int(m_analysis_waiting_data_json['url_hunter_queue_waiting_count'])
            m_json['analysis_consuming_url_count'] = int(m_analysis_waiting_data_json['url_crawling_queue_consuming_count']) + int(m_analysis_waiting_data_json['url_hunter_queue_consuming_count'])

            m_json['analysis_waiting_file_count'] = int(m_analysis_waiting_data_json['file_crawling_queue_waiting_count'])
            m_json['analysis_consuming_file_count'] = int(m_analysis_waiting_data_json['file_crawling_queue_consuming_count'])
        except Exception as ex:
            print('error')

        return jsonify(m_json)

    @api.response(403, 'Not Authorized')
    def post(self):
        api.abort(403)

@api.route('/monitoring/system_info')
class ReportSystemInfo(Resource):

    def get(self):

        m_json = {}
        try:
            m_redis = redis.Redis(host=c_redis_ip, port=6379, password=c_redis_pw, charset="utf-8", decode_responses=True)
            m_resource_info = json.loads(m_redis.get('system_resource_monitoring_data'))
            m_server_status = json.loads(m_redis.get('server_status_data'))

            # {
            #     "cpu_model_name": " Intel Xeon Processor (Cascadelake)",
            #     "cpu_core": 1,
            #     "cpu_per": 15.41,
            #     "memory_total": 33672155136,
            #     "memory_usage": 19651874816,
            #     "memory_per": 58.36,
            #     "disk_total": 311993479168,
            #     "disk_usage": 111788941312,
            #     "disk_per": 35.83,
            #     "network_usage": 23007,
            #     "network_per": 0.02,
            #     "network_speed": "1000"
            # }
            # {
            #     "url_crawler_status": "normal",
            #     "file_crawler_status": "normal",
            #     "url_hunter_status": "normal",
            #     "zombiezero_status": "normal",
            #     "file_ai_status": "normal",
            #     "url_ai_status": "normal"
            # }

            m_json['system_resource_monitoring_data'] = m_resource_info
            m_json['server_status_data'] = m_server_status
        except:
            print('error')

        return jsonify(m_json)

    @api.response(403, 'Not Authorized')
    def post(self):
        api.abort(403)

@api.route('/monitoring/ai_analysis_info')
class ReportAiAnalysisInfo(Resource):

    def get(self):
        m_start_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
        m_end_date = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

        resp = es.search(index="analysis*", query={
                                'bool': {
                                    'filter': [
                                        {'term': {'type.keyword': 'file'}},
                                        {'range': {'reg_date': {'gte': m_start_date}}},
                                        {'range': {'reg_date': {'lte': m_end_date}}}
                                    ]
                                }
                            }, size=0,
                         aggs={
                             'agg_malware_type': {
                                 'terms': {'field': 'ai_file_analysis_result.detail_info.data.malware.keyword', 'size': 10}
                             }
                         }
                         )

        m_file_result = resp['aggregations']['agg_malware_type']['buckets']

        resp = es.search(index="analysis*", query={
                                'bool': {
                                    'filter': [
                                        {'term': {'type.keyword': 'url'}},
                                        {'range': {'reg_date': {'gte': m_start_date}}},
                                        {'range': {'reg_date': {'lte': m_end_date}}}
                                    ]
                                }
                            }, size=0,
                         aggs={
                             'agg_malware_type': {
                                 'terms': {'field': 'ai_url_analysis_result.detail_info.msg.prediction_result.keyword', 'size': 10}
                             }
                         }
                         )

        m_url_result = resp['aggregations']['agg_malware_type']['buckets']

        m_json = {}
        m_json['ai_file_result'] = m_file_result
        m_json['ai_url_result'] = m_url_result

        return jsonify(m_json)

    @api.response(403, 'Not Authorized')
    def post(self):
        api.abort(403)

@api.route('/monitoring/daily_analysis_info')
class ReportDailyAnalysisInfo(Resource):

    def get(self):
        m_start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        m_end_date = datetime.now().strftime('%Y-%m-%d')
        # , 'aggs': {'ai_malware_type': {'terms': {'field': 'ai_file_analysis_result.detail_info.data.detection.keyword'}}}
        # data date series
        resp = es.search(index="analysis*", query={
            'bool': {
                'filter': [
                    {'term': {'type.keyword': 'file'}},
                    {'range': {'reg_date': {'gte': m_start_date, 'lte': m_end_date}}}
                ]
            }
        }, size=0,
                         aggs={
                             'date_malware': {
                                 'date_histogram':
                                     {
                                         'field': 'reg_date',
                                         'calendar_interval': 'day',
                                         'min_doc_count': 0,
                                         'extended_bounds': {'min': m_start_date, 'max': m_end_date}
                                     }
                             }
                         }
                         )

        m_collect_result = resp['aggregations']['date_malware']['buckets']

        # ai line data
        resp = es.search(index="analysis*", query={
            'bool': {
                'filter': [
                    {'term': {'type.keyword': 'file'}},
                    {'term': {'ai_file_analysis_result.detail_info.data.detection.keyword': 'Malware'}},
                    {'range': {'reg_date': {'gte': m_start_date, 'lte': m_end_date}}}
                ]
            }
        }, size=0,
                         aggs={
                             'date_malware': {
                                 'date_histogram':
                                     {
                                         'field': 'reg_date',
                                         'calendar_interval': 'day',
                                         'min_doc_count': 0,
                                         'extended_bounds': {'min': m_start_date, 'max': m_end_date}
                                     }
                             }
                         }
                         )

        m_aimalware_result = resp['aggregations']['date_malware']['buckets']

        # zzero line data
        resp = es.search(index="analysis*", query={
            'bool': {
                'filter': [
                    {'term': {'type.keyword': 'file'}},
                    {'term': {'zzero_analysis_result.detail_info.total_result.keyword': 'malware'}},
                    {'range': {'reg_date': {'gte': m_start_date, 'lte': m_end_date}}}
                ]
            }
        }, size=0,
                         aggs={
                             'date_malware': {
                                 'date_histogram':
                                     {
                                         'field': 'reg_date',
                                         'calendar_interval': 'day',
                                         'min_doc_count': 0,
                                         'extended_bounds': {'min': m_start_date, 'max': m_end_date}
                                     }
                             }
                         }
                         )

        m_zzeromalware_result = resp['aggregations']['date_malware']['buckets']

        m_json = {}
        m_json['collect_result'] = m_collect_result
        m_json['ai_malware_result'] = m_aimalware_result
        m_json['zzero_malware_result'] = m_zzeromalware_result

        # vaccine top 3
        resp = es.search(index='analysis*', query={
            'bool': {
                'filter': [
                    {'term': {'type.keyword': 'file'}},
                    {'range': {'reg_date': {'gte': m_start_date, 'lte': m_end_date}}}
                ]
                , 'must_not': [{'match': {'zzero_analysis_result.detail_info.vaccine_detail_result.keyword': ''}}]
            }
        }, size=0,
                         aggs={
                             'malware_type': {'terms': {'field': 'zzero_analysis_result.detail_info.vaccine_detail_result.keyword', 'size': 3}}
                         }

                         )

        m_vaccine_top3 = resp['aggregations']['malware_type']['buckets']

        # yara top 3
        resp = es.search(index='analysis*', query={
            'bool': {
                'filter': [
                    {'term': {'type.keyword': 'file'}},
                    {'range': {'reg_date': {'gte': m_start_date, 'lte': m_end_date}}}
                ]
                , 'must_not': [{'match': {'zzero_analysis_result.detail_info.detail_analysis_info.static_yara_rule.name.keyword': ''}}]
            }
        }, size=0,
                         aggs={
                             'malware_type': {'terms': {'field': 'zzero_analysis_result.detail_info.detail_analysis_info.static_yara_rule.name.keyword', 'size': 3}}
                         }

                         )

        m_yara_top3 = resp['aggregations']['malware_type']['buckets']

        # ai top 3
        resp = es.search(index='analysis*', query={
            'bool': {
                'filter': [
                    {'term': {'type.keyword': 'file'}},
                    {'range': {'reg_date': {'gte': m_start_date, 'lte': m_end_date}}}
                ]
                , 'must_not': [{'match': {'ai_file_analysis_result.detail_info.data.malware.keyword': ''}}]
            }
        }, size=0,
                         aggs={
                             'malware_type': {'terms': {'field': 'ai_file_analysis_result.detail_info.data.malware.keyword', 'size': 3}}
                         }

                         )

        m_ai_top3 = resp['aggregations']['malware_type']['buckets']

        m_json['vaccine_top3'] = m_vaccine_top3
        m_json['yara_top3'] = m_yara_top3
        m_json['ai_top3'] = m_ai_top3

        return jsonify(m_json)

    @api.response(403, 'Not Authorized')
    def post(self):
        api.abort(403)

@api.route('/monitoring/urlhunter_info')
class ReportUrlHunterInfo(Resource):

    def get(self):
        m_mysql_ip = '125.7.199.176'
        m_mysql_id = 'admin'
        m_mysql_pw = 'password'

        m_json = {}
        m_json['url_list'] = []

        # (1) MYSQL ??????
        connection = mysql.connector.connect(host=m_mysql_ip, database='urlhunter_flask', user=m_mysql_id, password=m_mysql_pw)

        with connection:
            with connection.cursor(buffered=True) as cur:
                cur.execute('SELECT no, site_name, screenshot, similarity, defaced, reputation_result, ai_result FROM sites order by reg_date desc limit 0,8')
                while True:
                    records = cur.fetchmany(8)
                    if len(records) != 0:
                        for data in records:
                            m_is_detected = 'N'
                            if (data[3] <= 0.6 or data[4] == 1 or data[5] == 'Y' or data[6] == 'Y'):
                                m_is_detected = 'Y'
                            m_json['url_list'].append({'no': data[0], 'site_name': data[1], 'screenshot': data[2], 'is_detected': m_is_detected})
                    else:
                        break

                cur.execute('SELECT count(*) FROM sites WHERE similarity<=0.6 or defaced=1 or reputation_result="Y" or ai_result="Y"')
                m_url_hunter_detect_count = cur.fetchone()[0]
                cur.execute('SELECT count(*) FROM sites')
                m_url_hunter_all_count = cur.fetchone()[0]
                m_url_hunter_normal_count = m_url_hunter_all_count - m_url_hunter_detect_count
        connection.close()

        m_json['total_detect_count'] = m_url_hunter_detect_count
        m_json['total_normal_count'] = m_url_hunter_normal_count
        return jsonify(m_json)

    @api.response(403, 'Not Authorized')
    def post(self):
        api.abort(403)



if __name__ == '__main__':
    #app.run(debug=True)
    #HOST = os.environ.get('SERVER_HOST', '192.168.1.229')
    HOST = '192.168.1.229'
    PORT = 8085
    app.run(HOST, PORT)
