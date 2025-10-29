import logging
from pathlib import Path

class LoggerUtil:
    @staticmethod
    def get_logger(name: str):
        """
        Retourne un logger préconfiguré avec format et handlers uniformes (niveau INFO par défaut).
        Le fichier log est automatiquement créé dans logs/<name>.log
        """
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

        if not logger.handlers:
            # Console handler
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)

            # File handler
            log_path = Path("/usr/src/logs") / f"{name}.log"
            # Crée automatiquement le dossier logs si absent
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path, mode='a', encoding='utf-8')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        return logger
