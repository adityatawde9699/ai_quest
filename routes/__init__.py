from routes.quest import quest_bp
from routes.operations import operations_bp
from routes.admin import admin_bp
from routes.auth import auth_bp
from routes.qr import qr_bp
from routes.results import results_bp
from routes.rounds import rounds_bp
from routes.scores import scores_bp
from routes.teams import teams_bp
from routes.batches import batches_bp


def register_routes(app):
    for blueprint in (auth_bp, admin_bp, teams_bp, batches_bp, rounds_bp, qr_bp, scores_bp, results_bp, quest_bp, operations_bp):
        app.register_blueprint(blueprint)
