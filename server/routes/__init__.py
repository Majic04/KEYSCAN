"""Les adresses (routes) de l'application, rangées par sujet. Chaque fichier déclare un « Blueprint » Flask."""
from . import documents, dossiers, keywords, results, session, settings

ALL = [session.routes, keywords.routes, dossiers.routes, documents.routes, results.routes, settings.routes]
