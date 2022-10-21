from flask import Flask, jsonify
from flask_cors import CORS
from flask_restplus import Api, Resource, fields
from datetime import datetime
from elasticsearch import Elasticsearch

import json

app = Flask(__name__)
CORS(app)
api = Api(app, version='1.0', title='PIOLINK Elasticsearch API',
    description='PIOLINK Elasticsearch API for dashboards',
)

es = Elasticsearch('http://125.7.199.174:9200', basic_auth=('elastic', 'npCore-5317'))

@api.route('/es_count')
class EsRoot(Resource):
    def get(self):
        resp = es.count()
        return resp['count']

@api.route('/es')
class EsRoot(Resource):
    def get(self):
        resp = es.search(index="*", query={"match_all": {}},size=100, from_=0)
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


if __name__ == '__main__':
    app.run(debug=True)
