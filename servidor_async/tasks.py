from celery import shared_task
from servidor_async.signbox_models import VitacoraFirmado, billingSignboxProd, task_asincrono, detalleFirma, webhookIP_Signbox, firma_asincrona, Imagen, PerfilSistema, LicenciasSistema, UsuarioSistema, signboxAPI, UserSigngo, ArchivosPDFSignbox
from django.http import JsonResponse
import json
from django.db.models import Q
import requests
import time
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.timezone import now
from urllib.parse import urlparse
from django.http import HttpResponse
import zipfile
import os
from django.core.files.base import ContentFile
import io
from datetime import datetime


@shared_task
def tarea_asincrona(TokenEnvio):
    
    get_task = task_asincrono.objects.using('signgo').get(transaccion_tarea=TokenEnvio)
    
    if get_task.transaccion_tipo == 'Firma':
        procesar_documentos(TokenEnvio)
        get_task.estado = 'Finalizado'
        get_task.save()
        descontar_creditos(TokenEnvio)
        enviar_correo("Proceso de firma completado", TokenEnvio)
        return 'procesando documentos'
    elif get_task.transaccion_tipo == 'empaquetar_archivos':
        # OBTENER LA TAREA Y EL ID DEL ENVIO QUE HAY QUE ENCRIPTAR
        archivos_to_encriptar = get_task.tx_task # CONTIENE EN TOKEN DEL ENVIO CON EL QUE SE ASOCÍAN LOS ARCHIVOS QUE SE FIRMARON
        archivos_zip = encriptar_documentos(archivos_to_encriptar)
        url_zip = guardar_archivo('media/archivos_zip/', 'documentos_historial', archivos_zip)
        enviar_correo = enviar_correo_archivo_zip("archivo_zip", f'{get_task.usuario.first_name} {get_task.usuario.last_name}', get_task.usuario.email, url_zip, "Archivos listos para descarga", "Los archivos solicitados se han procesado con éxito y pueden descargarse desde el siguiente enlace")
        get_task.estado = 'Finalizado'
        get_task.save()     
        return 'empaquetando documentos'
    
    return 'tipo de tarea no encontrado'

def procesar_documentos(TokenEnvio):
    try:
        idsAPI = []
        find_firmas = list(detalleFirma.objects.using('signgo').filter(TokenAuth=TokenEnvio)) 
        for i, firma in enumerate(find_firmas):            
            coordenadasFirma = f'{firma.p_x1},{firma.p_y1},{firma.p_x2},{firma.p_y2}'
            idFirma = firmar_documento(TokenEnvio, coordenadasFirma, str(int(firma.pagina)-1), firma.TokenAuthArchivo, firma.documento)
            if idFirma == "error:Exception('Certificate not valid',)":
                reasonError = "Certificado de firma electrónica vencido"
                raise Exception(reasonError)
            usuario_id = get_usuario_firmante(TokenEnvio)
            saveIDFile(firma.nombre_documento,firma.TokenAuthArchivo,TokenEnvio,"Pendiente",usuario_id,idFirma)
            idsAPI.append(idFirma)
            time.sleep(0.5)
            
            if firma.firma_multiple:
                while True:
                    # verificar el documento
                    validar_status_firma = VitacoraFirmado.objects.using('signgo').get(IDArchivoAPI=idFirma)
                    if validar_status_firma.EstadoFirma == "Firmado":
                        print(f'Estado de documento firmado: {validar_status_firma.EstadoFirma}')   
                        buscar_documentos = detalleFirma.objects.using('signgo').filter(
                            TokenAuth=firma.TokenAuth,
                            firma_multiple=True,
                            nombre_documento=firma.nombre_documento
                        )
                        
                        # Actualiza los documentos en la base de datos
                        for archivo in buscar_documentos:
                            archivo.documento = validar_status_firma.url_archivo
                            archivo.save()
                            
                        # Actualiza también los objetos en la lista find_firmas que coincidan
                        for j in range(i+1, len(find_firmas)):
                            if (find_firmas[j].TokenAuth == firma.TokenAuth and 
                                find_firmas[j].firma_multiple == True and 
                                find_firmas[j].nombre_documento == firma.nombre_documento):
                                find_firmas[j].documento = validar_status_firma.url_archivo
                        break
            else:
                None    
            
        return JsonResponse({'success': True,'data': 'Documentos Firmados'})
    except Exception as e:
        raise Exception(f'Error al firmar documentos: {e}')
    
def firmar_documento(TokenEnvio, CoordenadasFirma, PaginaFirma, TokenArchivo, ArchivoFirmar):
    try:
        UsuarioCliente, ContraseñaCliente, PinCliente = get_credenciales_certificado(TokenEnvio)
        protocolo_webhook, ip_webhook = get_webhook()
        dataUrlOut = f'{protocolo_webhook}://{ip_webhook}/result/{TokenArchivo}'
        dataUrlBack = f'{protocolo_webhook}://{ip_webhook}/services/{TokenArchivo}'
        UsuarioFirmante = get_usuario_firmante(TokenEnvio)
        UsuarioEstilo = get_estilo_estampa_grafica(UsuarioFirmante)
        UsuarioLicencia = get_licencia_usuario(UsuarioFirmante)
        EnvLicencia = get_env_licencia(UsuarioLicencia)
        UsuarioIdentifier = certificate_identifier(UsuarioCliente, ContraseñaCliente, EnvLicencia)
        UsuarioBilling, PasswordBilling = get_billing_licencia(UsuarioLicencia)
        EndpointAPI = get_endpoint_API()
        
        dataTexto = []
        dataTexto, rubricaGeneral, rubricaTamaño = get_contenido_rubrica(UsuarioEstilo)
        ContenidoRubrica = get_rubrica(dataTexto)
        
        create_payload = get_payload(dataUrlOut,dataUrlBack,EnvLicencia,UsuarioCliente,ContraseñaCliente,
                                    PinCliente,ContenidoRubrica,rubricaGeneral,rubricaTamaño,UsuarioBilling,
                                    PasswordBilling,CoordenadasFirma,PaginaFirma,UsuarioIdentifier)

        ArchivoUsuario = get_archivo_firmar(ArchivoFirmar)
        id_request = request_api_sign(EndpointAPI,create_payload,ArchivoUsuario)
        return id_request
    except Exception as e:
        raise Exception(f'Error al firmar documento: {e}')

def get_webhook():
    try:
        getDataWebhook = webhookIP_Signbox.objects.get(id=1)
        protocolo = "https" if getDataWebhook.protocol == "1" else "http"
        return protocolo, getDataWebhook.ip
    except Exception as e:
        raise Exception(f'Error al obtener datos de webhook: {e}')
       
def actualizar_estado_tx(TokenEnvio, estado):
    try:
        get_task = task_asincrono.objects.using('signgo').get(transaccion_tarea=TokenEnvio)
        get_task.estado = estado
        get_task.save()
        return JsonResponse({'success': True,'data': 'Estado Actualizado'})
    except Exception as e:
        raise Exception(f"Error al actualizar estado: {str(e)}")
    
def get_credenciales_certificado(TokenEnvio):
    try:
        get_transaccion_tarea = task_asincrono.objects.using('signgo').get(transaccion_tarea=TokenEnvio)
        get_credenciales = firma_asincrona.objects.using('signgo').filter(usuario=get_transaccion_tarea.usuario.pk).last()
        return get_credenciales.c1, get_credenciales.c2, get_credenciales.c3
    except Exception as e:
        raise Exception(f'Error al obtener certficado: {e}')
    
def get_usuario_firmante(TokenEnvio):
    try:
        get_usuario = task_asincrono.objects.using('signgo').get(transaccion_tarea=TokenEnvio)
        return get_usuario.usuario.pk
    except Exception as e:
        raise Exception(f'Error al recuperar usuario firmante: {e}')
    
def get_estilo_estampa_grafica(UsuarioFirmante):
    try:
        if Imagen.objects.filter(UsuarioSistema=UsuarioFirmante, is_predeterminado=True).exists():
            getDataEstilo = Imagen.objects.get(UsuarioSistema=UsuarioFirmante, is_predeterminado=True)
            getIdEstilo = getDataEstilo.id
        else: 
            getIdEstilo = None
        return getIdEstilo
    except Exception as e:
        raise Exception(f'Error al obtener estilo de firma: {e}')
    
def get_licencia_usuario(usuarioID):
    try:
        validate_perfil = PerfilSistema.objects.get(usuario=usuarioID)
        if validate_perfil.empresa == None:
            validate_user = UsuarioSistema.objects.get(UsuarioGeneral=usuarioID)
            validate_licencia = LicenciasSistema.objects.filter(
                Q(tipo='Firma Agil') | Q(tipo='CorporativoAuth') | Q(tipo='CorporativoOneshotAuth') | Q(tipo='CorporativoOneshotVideoAuth'),
                usuario=validate_user.id
            ).order_by('-id').last()
        else:            
            validate_licencia = LicenciasSistema.objects.filter(
                Q(tipo='Firma Agil') | Q(tipo='CorporativoAuth') | Q(tipo='CorporativoOneshotAuth') | Q(tipo='CorporativoOneshotVideoAuth'),
                empresa=validate_perfil.empresa.id
            ).order_by('-id').last()
              
        if validate_licencia.licencia_vencida():
            raise Exception("Licencia Expirada")
            
        if int(validate_licencia.porcentaje) >= 100:
            return Exception("Creditos Agotados")
        else: 
            return json.dumps({"success": True, "data": "OK", "tipo_licencia": validate_licencia.env, "id_licencia": validate_licencia.id})                

    except Exception as e:
        raise Exception(f'No se ha podido encontrar su licencia: {e}')
    
def get_env_licencia(LicenciaUsuario):
    try:
        validate_licencia_parse = json.loads(LicenciaUsuario)
        envSignbox = "sandbox" if validate_licencia_parse['tipo_licencia'] == 'sandbox' else "prod"
        return envSignbox
    except Exception as e:
        raise Exception(f'Error al obtener env de licencia: {e}')
    
def certificate_identifier(usuario, contraseña, env):
    try:
        if env == 'sandbox':
            url = "https://cryptoapi.sandbox.uanataca.com/api/get_objects"
        else:
            url = "https://cryptoapi.uanataca.com/api/get_objects"
            
        payload = json.dumps({
            "username": usuario,
            "password": contraseña,
            "type": None,
            "identifier": None
        })
        headers = {'Content-Type': 'application/json'}
        response = requests.request("POST", url, headers=headers, data=payload)
        response_parse = json.loads(response.text)
        ckaid = response_parse['result'][-1]['ckaid']
        return ckaid
    except Exception as e:
        raise Exception(f'Error al obtener identifier: {e}')
    
def get_billing_licencia(LicenciaUsuario):
    try:
        validate_licencia_parse = json.loads(LicenciaUsuario)
        get_licencia = LicenciasSistema.objects.using('signgo').get(id=validate_licencia_parse['id_licencia'])
        return get_licencia.usuario_billing, get_licencia.contrasena_billing
    except Exception as e:
        raise Exception(f'Error al obtener las credenciales de billing: {e}')
    
def get_endpoint_API():
    try:
        getAPI = signboxAPI.objects.get(id=1)
        protocolAPI = "http" if getAPI.protocol == "0" else "https"
        url_API = protocolAPI + "://" + getAPI.ip + "/api/sign"
        return url_API
    except Exception as e:
        raise Exception(f'Erro al obtener endpoint de API {e}')   
    
def get_contenido_rubrica(EstiloUsuario):
    try:
        dataTexto = []
        if Imagen.objects.filter(id=EstiloUsuario).exists():
            personalizacion = Imagen.objects.get(id=EstiloUsuario)
            dataTexto.append("Firmado digitalmente por: $(CN)s") if personalizacion.isNombre else None
            dataTexto.append("Fecha: $(date)s") if personalizacion.isFecha else None
            dataTexto.append('"Ciudad de Guatemala, $(C)s"') if personalizacion.isUbicacion else None
            rubricaGeneral = personalizacion.Rubrica
            rubricaTamaño = personalizacion.dimensionesImagen
        else:
            dataTexto.append("Firmado digitalmente por: $(CN)s")
            dataTexto.append("Fecha: $(date)s")
            dataTexto.append('"Ciudad de Guatemala, $(C)s"')
            rubricaGeneral = '/9j/4AAQSkZJRgABAQEAeAB4AAD/2wBDAAIBAQIBAQICAgICAgICAwUDAwMDAwYEBAMFBwYHBwcGBwcICQsJCAgKCAcHCg0KCgsMDAwMBwkODw0MDgsMDAz/2wBDAQICAgMDAwYDAwYMCAcIDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAz/wAARCAGUAtADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD9/KKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiikLbaAA8imbzj+uaJZBsqKW6SIFpGCIByW4ov0E5Rjqx27nr+tODMeleafED9qjwV8OTKl9rdm08XBihbzJM+mFzXzj8UP8AgonrOqiaDwzALJWJCS3KAvj1Aya+gyzhTM8f/Ag7d3oj8v4q8Y+GOH4/7biIuWvuxactPmfak+oJAh3uq7epLYFct4i+N/hjwgrHUte021wcANcLkn0xmvzp8T/Hbxl42Df2n4j1OcOeUSUxKfwXFcrIhkdnJyX5Yk8mvv8ABeFFS18XW+UVf8XY/nXPfphYaMnHKMG2u85W/BX/ADP0C8Rft6fD/Roz5eqtcvnAEULtz+WK891n/gpnp8TSrp+j6lKUPDsq7T/49mvjxRtxgU4se/T6V9RhfDTK6etTml6v/gH5Rmn0puMMXf2XJSXknf8AFn0ndf8ABSjxJdq/kWFjH/d3If15rB1D/god49ntiIRpyNnhhGeK8JJ4NHRhXrw4KyaO1FHxlfx542r6vGNeh9e/sp/ts658QfiLaeH/ABJ5LNqQYQSQx4+dVLYP4A19YwufU1+bP7IEvl/tK+E9w5NzKBx1/cvX6SRt8nA69q/GfEDKMPgMeqeGjypxT/Fn9vfRv4wzLiDhqeJzao6lSNRpN72sn+pYByKWmxfcp1fDn9DhRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFNZ9poAUtik31G8ucf1pjzjd0OfWj1E3YfLJh8YzUU95HaRlnZUAGSWOMCuE+L37SvhX4OWz/wBr6jHHdbN6WyHfM/phRXxV8ef2t/E3xdv54re4utK0SRtotlfDSL/tEdPpX1OQcJY3NZrkXJDu9v8Agn4/4i+NORcJU3GvNVa3SEWr38+x9VfFz9uPwb8OXuLOK6bVNSi48i1G/B926CvkX4s/tUeMPirqdyG1a403SZSdlnA23A9Cwwa84hOFG4ZHTPtUbjzD1I54AHFftuRcB4DANTkueXd/5H8H8d/SA4l4kboxn7Cl/LDt5vdixRp5rMy5ZurHqT70owF6c+uaRkKLS19tGMU7R2PwmpUlOXPKTbYpb5QAMU3BPeloq7Ii7vcSlJJpC2DS4pWSFYTOPSjdheBn6UF+aGJCEjjbz16VLlpqVGDk7JHrX7Emm/2n+0joBALNZpLMeOB8hX/2av0T27R+HFfG3/BPH4IavaeMJ/FuoWklpZG18i0Eow028glgPTgdfWvskHJHGecV/NviLj6eIzb93JNRSX9fef6gfRk4fxeWcHr61BxlUnKVnppol99iWEYj9afTYz8tOr4U/om99QooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKQnApabKcRmgAEoIqOSUMxHtSB8L16iqOr6xbaJYy3dzMkNvGhZ5HfARRzmmk2+WOrM6lSNODqTaSW7Jru5S2hMjsFVRkk9hXzP8AtI/t22HhgX2i+GCb3UdhiN2hHlW7nuD3I9q8w/au/bFvfiLrtxo3hm8ubTQolMcsyHb9s/3SOQP518/rHsOB2/X3r9f4R8Pfa2xWY6do/wCZ/EfjH9JOVCpPKOGJaq6lU38rR/zLWqaxda/qMt5qFxLeXk7b3nlYs7H69vpVZpml+9n2pdmDSAV+00qUKcVGmrJH8OYjFVK9R1qzcpt3be9xwbEWKaOOlAbIpGkVRyRjvWlrmCvshzEseaKqy6rBAeDn6VTn13evybh9a1jSlY2jh5tGtjio5bqOEfMw/OsGW+lbrKx9s1B5m9s5NaqhLqdEcJ3N2TW7Ze5b8KrvryL91TWWzE9f0pj3KxLkkenNaxwyZtHCRNN/ER9MYp+l/EZfD+s2141pHfpBIrm1l4SXB7nBrnbjUA4wvf0qnI5c5x0rSWCpzi4z2Z6eDo+ynGpHdNNH6UfsL/tRal+0jpOsrc6FBo9toxiiiaC48xZSQ2R0GMYH519ED+dfN/8AwTW+FjfDr4FfapU2Nrkv20ZGCQyjFfSS4LV/HXE8MPHMqsMKrQvZddj/AFq8Np42fDuFq5i71JRu+npp6WHoNq06kT7tLXiH3KCiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACjOKKbIMigAdsCmO/yHPSmsoH196q6nqVvpljJPPMkUEQLO7nAGKNeblRnOpGEeeo7LqVPEvijT/CejyXt/cxWltCpdnkfaFA6818DftS/tS33xk8XT2+l3lzbeHIR5McIbaLr1dh6H0rO/bi/ag/4Xh46j0/SZWXw9pJeNWDELePnBfHoMYH414tba5JBjzVyK/euBuBHQhHH4yPvy2i+nn6n8A+PvjZiM0qTyHI52oxdpST1nbovL8zcddo4puTmoLHVY5kP+r5/vHmln1KKEYLjPpmv1VRt0P499nO92rk5+Tv9aheYRcscDPrWdeawzNiP7uKz2LSPkuBWtOi2rG1LCOXvSNW78QAAiIfjWdNemc5JOT6VCRs/jFMM4ByWH511rDpHZCjFfCSM+aKha+jB61DPq521tGDNVTky3nApj3SRrzWdNfmVeBVfdmt1SOlUH1L1xqPmn5e1VJpzIADTdu40FCorRQtqaxhFArYarWjaPN4o1m0022GZ7+ZLeIerMwA/nVWFtr59Oa9q/YJ+HM3xA/aZ0QxRA2ujE39y23IQKMKM9MliOPavG4gx8MDgauIntGL++x9Vwhk1TNc6w2ApK/tJxXyvr+B+lvgHQo/DPgrTdPjiCJawJEFUYC4AFbYHzdKdEMEfSpK/iupNzm5y6u5/rbhcPGhRhQjtFJfcIvApaKKg6AooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiikz1oAWmO2GFOU5qKYk/j19qARHM/GTgfWvhD/AIKOftbtr2qS+BvDlxm1tdy6pcpIQHYjBiGOuM817f8Atx/teWn7PfhddNtMXXiDVIXEEKtzEuCBI3tmvzO1XXlR/tV5OWlmzI7McmRiSST781+w+GPBn1qss0xUbxXwro/P5H8ofSD8UpYKg+HsqlerL42t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4k/sNfDX4pa5JqGp+GNO+2THMsscIUynOctxzXe/Dv4UaB8KtBTTvD2lWWk2i9Ut4Qm49MnHegDooySgz170kz7F/H0pUXaKJE3r6UAeM/ts+MZLT4PyeF7Jv+J54+mXw/YIp+dTN8skg7/JHvfP+zXmWmf8EmPC+n6fbwx+OfiJDHBEscaRaqAiADoo28CvpbV/h1pWs+KbLWrq2im1DTlK20jKCYcgglfQ4JH41teVujPH0oA+VP2Wrf8A4ZG+PGq/B6f7ddaJrJbWfD+pXcu97hmUGWJ2wB5m8Stgdq+sB0rC1rwHpniDWrC/u7OGa60yXzrWRo8tC20r8p7cE/nW7QAV4b+27Ksem/D8vhUTxlpxLE4C/Oete5VznxJ+F+h/FrQv7L8Q6bbarYCRZRDPHvUOOjfUUAZPxH/aD8H/AAt0K5v9e8Q6ZZQWqlivnK8sh7KiAlmY9gBk15n+zZoniX4u/HfWfir4j0Sbw7Yvpy6P4fsbhgbh7Yv5jzuP4C+I/l6jac13/g79lP4e+BdYjvtN8J6Nb3kZzHN9mXdH9K9Chh8gYySO2e1AElI7bEJ9BS0jjKH6dqAPnX9svwzH+0V418KfCgXd1bwajK2tazPaSbJbS1t/9Xg9AzTNHjPZW9K5bUf+CS/he8sLiGXx58R5o54zG6SaqGVlIxgjb0r6as/BOm2Hiu61uKzhXU7uFbeS42fOyKSQufTJrY8oZz75oA+bf2ANAm+A2na78H76WS5ufBM6zWE8pO68sZ8skue+JBIp/wB2vpCB96k+/asv/hCLA+Mf7eMEX9p/ZjaCcJhvKJ3bSfrWuqBOg69fegBaKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKRV25+uaWigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAQrlgfSloooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA//9k='
            rubricaTamaño = '720, 404'
            
        return dataTexto, rubricaGeneral, rubricaTamaño
    except Exception as e:
        raise Exception(f'Error al obtener estampa grafica: {e}')

def get_rubrica(Contenido):
    try:
        dataTexto = []
        dataTexto = Contenido
        
        paragraph_format = {
            "font": ["Universal-Italic", 10],
            "align": "right",
            "data_format": {
                "timezone": "America/Guatemala",
                "strtime": "%d/%m/%Y %H:%M:%S%z"
            },
            "format": dataTexto
        }
        paragraph_format_list = [paragraph_format]
        paragraph_format_json = json.dumps(paragraph_format_list)
        return paragraph_format_json
    except Exception as e:
        raise Exception(f' {e}')      

def get_payload(dataUrlOut,dataUrlBack,EnvLicencia,UsuarioCliente,ContraseñaCliente,
                PinCliente,ContenidoRubrica,rubricaGeneral,rubricaTamaño,UsuarioBilling,
                PasswordBilling,CoordenadasFirma,PaginaFirma,UsuarioIdentifier):
    try:
        payload = {
            'url_out': dataUrlOut,
            'urlback': dataUrlBack,
            'env': EnvLicencia,
            'format': 'pades',
            'username': UsuarioCliente,
            'password': ContraseñaCliente,
            'pin': PinCliente,
            'level': 'BES',
            'paragraph_format': ContenidoRubrica,
            'img_name': 'uanataca.argb',
            'reason': 'Firma Electrónica',
            'img': rubricaGeneral,
            'img_size': rubricaTamaño,
            'billing_username': UsuarioBilling,
            'billing_password': PasswordBilling,
            'location': 'Guatemala, Guatemala',
            'position': CoordenadasFirma,
            'npage': PaginaFirma,
            'identifier': UsuarioIdentifier,
        }
        return payload
    except Exception as e:
        raise Exception(f' {e}')

def get_archivo_firmar(Archivo):
    try:
        url_archivo_prueba = Archivo
        descarga_archivo = requests.get(url_archivo_prueba)
        file_content = descarga_archivo.content
        return file_content
    except Exception as e:
        raise Exception(f' {e}')   

def request_api_sign(EndpointAPI,create_payload,ArchivoUsuario):
    try:
        files = {
            'file_in': ('PruebaFirma.pdf', ArchivoUsuario, 'application/pdf'),
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        response = requests.post(EndpointAPI, data=create_payload, files=files)
        
        return response.text
    except Exception as e:
        raise Exception(f'Error al obtener id de request sign: {e}')

def saveIDFile(nombreArchivo, tokenArchivo, tokenEnvio, estutusArchivo, usuarioEnvio, IDAPI):
    try:
        InstanceUser = UserSigngo.objects.get(id=usuarioEnvio)
        InserVitacora = VitacoraFirmado(
            TokenEnvio = tokenEnvio,
            NombreArchivo = nombreArchivo,
            TokenArchivo = tokenArchivo,
            UsuarioFirmante = InstanceUser,
            EstadoFirma = estutusArchivo,
            IDArchivoAPI = IDAPI
        )
        InserVitacora.save()
        return 'OK 200'
    except Exception as e:
        raise Exception(f'Error al guardar Bitacora de firmado: {e}')


def descontar_creditos(TokenEnvio):
    # CALCULO PARA DESCUENTO DE CREDITOS
    archivo_firmados = []
    archivos_enviados = VitacoraFirmado.objects.filter(TokenEnvio=TokenEnvio).order_by('-id')
    for archivo in archivos_enviados:
        getStatusFile = VitacoraFirmado.objects.get(IDArchivoAPI=archivo.IDArchivoAPI)
        archivo_firmados.append(archivo.IDArchivoAPI) if getStatusFile.EstadoFirma == "Firmado" else None
    cantidad_archivos_firmados = (len(archivo_firmados))
        
    usuario_licencia = get_usuario_firmante(TokenEnvio) 
       
    if cantidad_archivos_firmados > 0:    
        validate_perfil = PerfilSistema.objects.get(usuario=UserSigngo.objects.get(id=usuario_licencia))
        if validate_perfil.empresa == None:
            validate_user = UsuarioSistema.objects.get(UsuarioGeneral=validate_perfil.usuario.pk)
            licencia_usuario = LicenciasSistema.objects.filter(
                Q(tipo='Firma Agil') | Q(tipo='CorporativoAuth') | Q(tipo='CorporativoOneshotAuth') |          
                Q(tipo='CorporativoOneshotVideoAuth'),
                usuario=validate_user.pk
            ).last()
            licencia_usuario.consumo = licencia_usuario.consumo + int(cantidad_archivos_firmados)
        else:            
            licencia_usuario = LicenciasSistema.objects.filter(
                Q(tipo='Firma Agil') | Q(tipo='CorporativoAuth') | Q(tipo='CorporativoOneshotAuth') | 
                Q(tipo='CorporativoOneshotVideoAuth'),
                empresa=validate_perfil.empresa.id
            ).order_by('-id').last()
            licencia_usuario.consumo = licencia_usuario.consumo + int(cantidad_archivos_firmados)    
        licencia_usuario.save()
    return 5

def enviar_correo(asunto_mail, url1):
    try:
        
        get_user = VitacoraFirmado.objects.filter(TokenEnvio=url1).last()
        
        nombre_empresa = 'SignGo'
        nombre_remitente = 'El equipo'
           
        url = f'https://signgo.com.gt/firma_agil/signDocs/{url1}'
        
        context = {
            'data': url,
            'nombre': f'{get_user.UsuarioFirmante.first_name} {get_user.UsuarioFirmante.last_name}',
            'asunto': asunto_mail,
            'nombre_remitente': nombre_remitente,
            'nombre_empresa': nombre_empresa
        }
        
        template_html = render_to_string('plantilla_correo.html', context)
        
        
        destinatarios = [get_user.UsuarioFirmante.email]
        send_mail(asunto_mail, '', "notificaciones@signgo.com.gt", destinatarios, fail_silently=False, html_message=template_html)
        return json.dumps({"success": True, "data": "Enviado"})
    except Exception as e:
        print(f'send_mail: {e}')
        return json.dumps({"success": False, "error": f'send_mail: {str(e)}'})


def encriptar_documentos(documentos_to_encriptar):
    try:
        # OBTENER ARCHIVOS DE LA TRANSACCIÓN
        get_files = VitacoraFirmado.objects.using('signgo').filter(
            TokenEnvio=documentos_to_encriptar
        ).order_by(
            'NombreArchivo', 
            '-id'
        ).distinct(
            'NombreArchivo'
        )
        
        # OBTENER INDIVIDUALMENTE CADA URL
        for documento in get_files:
            # ACTUALIZAR CADA URL PREFIRMADA 
            validar_link = validar_url_prefirmada(documento.TokenArchivo)
            
            if not validar_link == 'OK':
                documento.url_archivo = validar_link
                documento.save()
         
                
        get_files = VitacoraFirmado.objects.using('signgo').filter(
            TokenEnvio=documentos_to_encriptar
        ).order_by(
            'NombreArchivo', 
            '-id'
        ).distinct(
            'NombreArchivo'
        )
        empaquetar_archivos = download_pdfs_and_zip(get_files)
        return empaquetar_archivos
    except Exception as e:
        raise ValueError("No fue posible descargar los archivos")


def validar_url_prefirmada(token_archivo):
    try:
        archivo = ArchivosPDFSignbox.objects.get(token_archivo=token_archivo)

        if archivo.url_firmada_expiracion and archivo.url_firmada_expiracion > now():
            return 'OK'
            
        nueva_url = archivo.get_presigned_url()
        return nueva_url
    
    except ArchivosPDFSignbox.DoesNotExist:
        return print(f'Archivo no encontrado')
    
    
def download_pdfs_and_zip(queryset):
    """
    Función para descargar PDFs desde un queryset y generar un ZIP como bytes
    """
    try:
        # Extraer URLs del queryset
        urls = [documento.url_archivo for documento in queryset]
        
        if not urls:
            return None
        
        # Crear ZIP en memoria como bytes
        zip_buffer = io.BytesIO()
        used_filenames = set()  # Para evitar nombres duplicados
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for i, url in enumerate(urls):
                try:
                    # Descargar PDF
                    pdf_response = requests.get(url, timeout=30)
                    pdf_response.raise_for_status()
                    
                    # Verificar que es un PDF
                    content_type = pdf_response.headers.get('Content-Type', '')
                    if 'pdf' not in content_type.lower():
                        print(f"Advertencia: {url} no parece ser un PDF")
                    
                    # Obtener nombre único del archivo
                    filename = get_unique_pdf_filename(url, pdf_response, i, used_filenames)
                    used_filenames.add(filename)
                    
                    # Agregar PDF al ZIP
                    zip_file.writestr(filename, pdf_response.content)
                    
                except Exception as e:
                    print(f"Error descargando {url}: {str(e)}")
                    continue
        
        # Obtener bytes del ZIP
        zip_buffer.seek(0)
        return zip_buffer.getvalue()
        
    except Exception as e:
        print(f'Error: {str(e)}')
        return None

def get_unique_pdf_filename(url, response, index, used_filenames):
    """
    Extrae el nombre del archivo PDF y asegura que sea único
    """
    # Obtener nombre base
    filename = get_pdf_filename(url, response, index)
    
    # Si el nombre ya existe, agregar contador
    if filename in used_filenames:
        name, ext = filename.rsplit('.', 1)
        counter = 2
        while f"{name}_{counter}.{ext}" in used_filenames:
            counter += 1
        filename = f"{name}_{counter}.{ext}"
    
    return filename


def get_pdf_filename(url, response, index):
    """
    Extrae el nombre del archivo PDF
    """
    # Intentar obtener desde Content-Disposition
    content_disposition = response.headers.get('Content-Disposition', '')
    if 'filename=' in content_disposition:
        import re
        match = re.search(r'filename[^;=\n]*=(([\'"]).*?\2|[^;\n]*)', content_disposition)
        if match:
            filename = match.group(1).strip('"\'')
            if filename.endswith('.pdf'):
                return filename
    
    # Obtener desde la URL
    parsed_url = urlparse(url)
    filename = parsed_url.path.split('/')[-1]
    
    # Asegurar extensión .pdf
    if not filename.endswith('.pdf'):
        if '.' in filename:
            filename = filename.rsplit('.', 1)[0] + '.pdf'
        else:
            filename = f"documento_{index + 1}.pdf"
    
    return filename


def enviar_correo_archivo_zip(tipo_correo, nombre_remitente, destinatario, url, asunto, mensaje):
    try:
        
        nombre_empresa = 'SignGo'
        nombre_remitente = 'El equipo'
        
        context = {
            'data': url,
            'nombre': nombre_remitente,
            'asunto': asunto,
            'nombre_remitente': nombre_remitente,
            'nombre_empresa': nombre_empresa,
            'mensaje_correo': mensaje
        }
        
        template_html = render_to_string('plantilla_correo.html', context)
        
        
        destinatarios = [destinatario]
        send_mail(asunto, '', "notificaciones@signgo.com.gt", destinatarios, fail_silently=False, html_message=template_html)
        return json.dumps({"success": True, "data": "Enviado"})
    except Exception as e:
        print(f'send_mail: {e}')
        return json.dumps({"success": False, "error": f'send_mail: {str(e)}'})
    
    
def guardar_archivo(ruta, nombre_carpeta_save, archivo):
    base_path = ruta
    nombre_carpeta = nombre_carpeta_save
    
    # Asegurar que existe la carpeta
    os.makedirs(os.path.join(os.path.abspath(os.getcwd()), base_path, nombre_carpeta), exist_ok=True)
    # Guardar el documento en el bucket
    nueva_archivo = ArchivosPDFSignbox()
    nueva_archivo.set_upload_paths(base_path, nombre_carpeta)
    
    # Preparar el contenido del archivo
    file_content = ContentFile(archivo)
    
    # Guardar el archivo en el bucket
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    nueva_archivo.archivo.save(f"Documentos_firmados_{now}.zip", file_content)
    nueva_archivo.save()
    
    # Generar URL prefirmada
    url_prefirmada = nueva_archivo.get_presigned_url()
    print(url_prefirmada)
    return url_prefirmada
