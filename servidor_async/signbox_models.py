from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.contrib.auth.models import User as DjangoUser
from django.contrib.auth import get_user_model
from pathlib import Path
from datetime import timedelta
from django.forms import ValidationError
from django.utils.timezone import now
import environ
import os

class UserSigngo(models.Model):
    id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    
    class Meta:
        managed = False
        db_table = 'auth_user'
        app_label = 'signgo_replicas'
        
class UsuarioSistema(models.Model):
    id = models.AutoField(primary_key=True)
    Nombres = models.CharField(max_length=50, null=True)
    Apellidos = models.CharField(max_length=50, null=True)
    Email = models.CharField(max_length=50, null=True)
    Celular = models.CharField(max_length=50, null=True)
    CUI = models.CharField(max_length=50, null=True)
    FechaRegistro = models.DateField(auto_now_add=True, null=True)
    Token = models.CharField(max_length=100, null=True)
    UsuarioGeneral = models.OneToOneField(UserSigngo, on_delete=models.CASCADE, null=True)
    
    def __str__(self):
        return self.id
    
    class Meta:
        managed = False
        db_table = 'app_usuariosistema'
        app_label = 'signgo_replicas'
        
class EmpresaSistema(models.Model):
    id = models.AutoField(primary_key=True)
    Nombre = models.CharField(max_length=50)
    NIT = models.CharField(max_length=50, null=True)
    Sector = models.CharField(max_length=50, null=True)
    NombreContacto = models.CharField(max_length=50, null=True)
    NumeroContacto = models.CharField(max_length=50, null=True)
    EmailContacto = models.CharField(max_length=50, null=True)
    FechaRegistro = models.DateField(auto_now_add=True, null=True)
    Estado = models.BooleanField(default=True)
    Token = models.CharField(max_length=100, null=True)
    
    class Meta:
        managed = False
        db_table = 'app_empresasistema'
        app_label = 'signgo_replicas'
        
class PerfilSistema(models.Model):
    id = models.AutoField(primary_key=True)
    empresa = models.ForeignKey(EmpresaSistema, null=True, blank=True, on_delete=models.CASCADE, related_name='usuarios')
    usuario = models.OneToOneField(UserSigngo, on_delete=models.CASCADE)
    Token = models.CharField(max_length=100, null=True)
    
    class Meta:
        managed = False
        db_table = 'app_perfilsistema'
        app_label = 'signgo_replicas'
        

class LicenciasSistema(models.Model):
    id = models.AutoField(primary_key=True)
    empresa = models.ForeignKey(
        EmpresaSistema, 
        on_delete=models.CASCADE, 
        related_name="licencias", 
        null=True, 
        blank=True
    )
    usuario = models.ForeignKey(
        UsuarioSistema, 
        on_delete=models.SET_NULL, 
        related_name="licencias", 
        null=True, 
        blank=True
    )
    tipo = models.CharField(max_length=50, null=True)
    modalidad = models.CharField(max_length=50, null=True)
    costo_tipo = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cantidad_creditos = models.IntegerField()
    cantidad_creditos_oneshot = models.IntegerField(default=0)
    cantidad_creditos_video = models.IntegerField(default=0)
    acumulado_creditos = models.IntegerField(null=True)
    acumulado_creditos_oneshot = models.IntegerField(default=0)
    acumulado_creditos_video = models.IntegerField(default=0)
    costo_creditos = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fecha_inicio = models.DateField(auto_now_add=True)
    fecha_fin = models.DateField()
    activa = models.CharField(max_length=50, null=True)
    usuario_billing = models.CharField(max_length=50, null=True)
    contrasena_billing = models.CharField(max_length=50, null=True)
    observaciones = models.TextField(null=True)
    consumo = models.IntegerField(null=True, default=0)
    consumo_oneshot = models.IntegerField(null=True, default=0)
    consumo_video = models.IntegerField(null=True, default=0)
    TokenAuth = models.CharField(max_length=100, null=True)
    porcentaje = models.FloatField(default=0, editable=False)
    porcentaje_oneshot = models.FloatField(default=0, editable=False)
    porcentaje_video = models.FloatField(default=0, editable=False)
    env = models.CharField(max_length=20, null=True)
    
    def save(self, *args, **kwargs):
        if self.acumulado_creditos > 0:
            self.porcentaje = (self.consumo / self.acumulado_creditos) * 100
        else:
            self.porcentaje = 0 
        
        if self.acumulado_creditos_oneshot > 0:
            self.porcentaje_oneshot = (self.consumo_oneshot / self.acumulado_creditos_oneshot) * 100
        else:
            self.porcentaje_oneshot = 0 
        
        if self.acumulado_creditos_video > 0:
            self.porcentaje_video = (self.consumo_video / self.acumulado_creditos_video) * 100
        else:
            self.porcentaje_video = 0 
        
        super().save(*args, **kwargs)
        
    def licencia_vencida(self):
        return self.fecha_fin < now().date()
    
    def clean(self):
        """Valida que la licencia esté asociada a una empresa o a un usuario."""
        if not self.empresa and not self.usuario:
            raise ValidationError("La licencia debe estar asociada a una empresa o a un usuario.")

    def __str__(self):
        return f"Licencia {self.id} ({self.tipo})"
    
    class Meta:
        managed = False
        db_table = 'app_licenciassistema'
        app_label = 'signgo_replicas'
        
        
##############################################################################################################


def user_directory_path(instance, filename):
    # Almacena el archivo en media/usuario_<id>/<nombre_de_archivo>
    return f'signbox/Rubrica/user_{instance.UsuarioSistema.id}/{filename}'

def dynamic_upload_to(instance, filename, base_path="media/", folder_name="default"):
    """Genera una ruta de subida dinámica."""
    return f"{base_path}/{folder_name}/{filename}"

# Modelos espejo (réplicas) de la base de datos signgo
class documentos(models.Model):
    status = models.CharField(max_length=15)
    secret = models.TextField()
    nameArchivos = ArrayField(models.TextField(null=True), null=True)
    idRequest = models.CharField(max_length=8, null=True)
    nameCarpeta = models.CharField(max_length=25, null=True)
    cantidadDocumentos = models.CharField(max_length=25, null=True)
    url_archivos = ArrayField(models.TextField(null=True), null=True)
    
    class Meta:
        managed = False
        db_table = 'signbox_documentos'
        app_label = 'signgo_replicas'
    
class VitacoraFirmado(models.Model):
    TokenEnvio = models.TextField()
    NombreArchivo = models.TextField()
    TokenArchivo = models.TextField()
    UsuarioFirmante = models.ForeignKey(UserSigngo, on_delete=models.CASCADE, null=True)
    EstadoFirma = models.TextField(null=True)
    IDArchivoAPI = models.TextField(null=True)
    FechaFirmado = models.DateField(auto_now_add=True, null=True)
    url_archivo = models.TextField(null=True)
    detalle_Firma = models.UUIDField(editable=False, unique=True, blank=True, null=True)
    
    class Meta:
        managed = False
        db_table = 'signbox_vitacorafirmado'
        app_label = 'signgo_replicas'

class billingSignboxProd(models.Model):
    user = models.CharField(max_length=50)
    password = models.CharField(max_length=100)
    status = models.CharField(max_length=25, null=True)
    
    class Meta:
        managed = False
        db_table = 'signbox_billingsignboxprod'
        app_label = 'signgo_replicas'
    
class billingSignboxSandbox(models.Model):
    user = models.CharField(max_length=50)
    password = models.CharField(max_length=100)
    status = models.CharField(max_length=25, null=True)
    
    class Meta:
        managed = False
        db_table = 'signbox_billingsignboxsandbox'
        app_label = 'signgo_replicas'

class signboxAPI(models.Model):
    ip = models.CharField(max_length=50, default='192.168.11.16:8080')
    protocol = models.CharField(max_length=10, null=True, default="0")
    
    class Meta:
        managed = False
        db_table = 'signbox_signboxapi'
        app_label = 'signgo_replicas'
    
class estiloFirmaElectronica(models.Model):
    UsuarioSistema = models.ForeignKey(UserSigngo, on_delete=models.CASCADE, null=True)
    Rubrica = models.TextField()
    imagen_archivo = models.ImageField(upload_to=user_directory_path, null=True)
    dimensionesImagen = models.CharField(max_length=50, null=True)
    isNombre = models.BooleanField(default=False, null=True)
    isFecha = models.BooleanField(default=False, null=True)
    isUbicacion = models.BooleanField(default=False, null=True)
    is_predeterminado = models.BooleanField(default=False, null=True)
    
    class Meta:
        managed = False
        db_table = 'signbox_estilofirmaelectronica'
        app_label = 'signgo_replicas'
        
BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, '.env.dev'))


class Imagen(models.Model):
    UsuarioSistema = models.ForeignKey(UserSigngo, on_delete=models.CASCADE, null=True)
    url_firmada_expiracion = models.DateTimeField(null=True, blank=True)
    Rubrica = models.TextField()
    imagen = models.FileField(upload_to="dynamic_path", null=True)
    dimensionesImagen = models.TextField(null=True)
    isNombre = models.BooleanField(default=False, null=True)
    isFecha = models.BooleanField(default=False, null=True)
    isUbicacion = models.BooleanField(default=False, null=True)
    is_predeterminado = models.BooleanField(default=False, null=True)
    presigned_url = models.TextField(null=True)
    
    class Meta:
        managed = False
        db_table = 'signbox_imagen'
        app_label = 'signgo_replicas'
        
class ArchivosPDFSignbox(models.Model):
    archivo = models.FileField(upload_to="dynamic_path", null=True, max_length=255)
    url_firmada_expiracion = models.DateTimeField(null=True, blank=True)
    token_archivo = models.TextField(null=True, blank=True)
    
    def __str__(self):
        return self.archivo.name

    def save(self, *args, **kwargs):
        # Define las rutas dinámicas
        base_path = getattr(self, "_base_path", "media/")
        folder_name = getattr(self, "_folder_name", "default")
        self.archivo.field.upload_to = lambda instance, filename: dynamic_upload_to(instance, filename, base_path, folder_name)
        super().save(*args, **kwargs)

    def set_upload_paths(self, base_path, folder_name):
        """Define el path base y la carpeta."""
        self._base_path = base_path
        self._folder_name = folder_name
    # 604800
    def get_presigned_url(self, expiration=604800):
        """Genera una URL firmada para el archivo."""
        import boto3
        from django.conf import settings
        from datetime import datetime, timezone

        s3_client = boto3.client(
            's3',
            aws_access_key_id=env('AWS_ACCESS_KEY'),
            aws_secret_access_key=env('AWS_SECRET_KEY'),
            region_name=env('AWS_REGION_NAME'),
        )
        bucket_name = env('AWS_BUCKET_NAME')
        object_name = self.archivo.name

        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': object_name},
            ExpiresIn=expiration
        )
        
        self.url_firmada_expiracion = datetime.now(timezone.utc) + timedelta(seconds=expiration)
        self.save(update_fields=["url_firmada_expiracion"])
        return url

    class Meta:
        managed = False
        db_table = 'signbox_archivospdf'
        app_label = 'signgo_replicas'

class credencialesCert(models.Model):
    user_system = models.ForeignKey(UserSigngo, on_delete=models.CASCADE, null=True)
    usuario_cert = models.CharField(max_length=25, null=True)
    pass_cert = models.CharField(max_length=25, null=True)
    
    class Meta:
        managed = False
        db_table = 'signbox_credencialescert'
        app_label = 'signgo_replicas'
    
class detalleFirma(models.Model):
    TokenAuth = models.CharField(max_length=100, null=True)
    documento = models.TextField()
    nombre_documento = models.CharField(max_length=100, null=True)
    pagina = models.CharField(max_length=50)
    p_x1 = models.CharField(max_length=50)
    p_x2 = models.CharField(max_length=50)
    p_y1 = models.CharField(max_length=50)
    p_y2 = models.CharField(max_length=50)
    status = models.CharField(max_length=50, default="NoFirmado")
    request_upload_document = models.TextField(null=True)
    firma_multiple = models.BooleanField(default=False, null=True)
    TokenAuthArchivo = models.UUIDField(editable=False, unique=True, blank=True, null=True)
    
    class Meta:
        managed = False
        db_table = 'signbox_detallefirma'
        app_label = 'signgo_replicas'
    
class detalleDocumento(models.Model):
    TokenAuth = models.CharField(max_length=100, null=True)
    url_documento = models.TextField()
    nombre_documento = models.TextField()
    
    class Meta:
        managed = False
        db_table = 'signbox_detalledocumento'
        app_label = 'signgo_replicas'
    
class task_asincrono(models.Model):
    usuario = models.ForeignKey(UserSigngo, on_delete=models.CASCADE, null=True)
    tx_task = models.TextField(null=True)
    transaccion_tarea = models.TextField(null=True)
    transaccion_tipo = models.TextField(null=True)
    fecha_creacion = models.DateField(auto_now_add=True, null=True)
    progreso = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estado = models.TextField(null=True)
    completado = models.BooleanField(default=False, null=True)
    
    class Meta:
        managed = False
        db_table = 'signbox_task_asincrono'
        app_label = 'signgo_replicas'
    
class firma_asincrona(models.Model):
    usuario = models.ForeignKey(UserSigngo, on_delete=models.CASCADE, null=True)
    c1 = models.TextField()
    c2 = models.TextField()
    c3 = models.TextField()
    
    class Meta:
        managed = False
        db_table = 'signbox_firma_asincrona'
        app_label = 'signgo_replicas'
        
class webhookIP_Signbox(models.Model):
    ip = models.CharField(max_length=50, default='192.168.11.16:8080')
    protocol = models.CharField(max_length=10, null=True, default="0")
    
    class Meta:
        managed = False
        db_table = 'signbox_webhookip_signbox'
        app_label = 'signgo_replicas'
        
