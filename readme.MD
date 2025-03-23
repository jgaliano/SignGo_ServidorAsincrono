pip install celery django-celery-results django-celery-beat redis
realizar migraciones
configuracion en archivo settings apuntando al servidor de redis
modición al archivo __init__.py
añadir arhivo tasks.py
crear archivo celery.py

enlazar servicio de redis(contenedor de docker de redis)
iniciar contenedor: docker run -d -p 6379:6379 redis

Inicilizar terminal de celery
celery -A sistema worker --loglevel=info --pool=solo