import json
import logging
import time
import threading

from flask import Blueprint, Response, jsonify, request, current_app

def create_analytics_blueprint(*, svc, repo, sync):
    bp = Blueprint("analytics_api", __name__, url_prefix="/api")