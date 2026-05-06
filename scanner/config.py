import os
import yaml
from dotenv import load_dotenv
from loguru import logger
import sys

# Charger les variables d'environnement (.env)
load_dotenv()

def setup_logging():
    """Configure loguru pour le projet."""
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>", level="INFO")
    logger.add("data/logs/scanner_{time:YYYY-MM-DD}.log", rotation="00:00", retention="30 days", level="DEBUG")

def load_config():
    """Charge la configuration YAML et injecte les variables d'env."""
    config_path = "config.yaml"
    if not os.path.exists(config_path):
        logger.error(f"Fichier de configuration {config_path} introuvable.")
        sys.exit(1)
        
    with open(config_path, 'r') as f:
        # On utilise SafeLoader et on gère manuellement l'interpolation des env vars simples
        config_str = f.read()
        
    # Remplacement simple des variables d'env ${VAR}
    for key, value in os.environ.items():
        placeholder = f"${{{key}}}"
        if placeholder in config_str:
            config_str = config_str.replace(placeholder, value)
            
    config = yaml.safe_load(config_str)
    return config

# Initialisation au chargement du module
setup_logging()
CONFIG = load_config()

# Vérification des secrets critiques
if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
    logger.warning("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant dans .env. Les notifications seront désactivées.")
