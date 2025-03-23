from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from .tasks import tarea_asincrona
import uuid
from servidor_async.signbox_models import VitacoraFirmado, billingSignboxProd, task_asincrono, detalleFirma, webhookIP_Signbox, firma_asincrona, PerfilSistema
import json
# from signbox.models import VitacoraFirmado


# Create your views here.
def helloworld(request):
    return render(request, 'helloworld.html')


@csrf_exempt
def tarea_async(request):
    mi_id_personalizado = f"tarea-{uuid.uuid4()}"
    try:
        respuesta_parse = json.loads(request.body)
        if task_asincrono.objects.using('signgo').filter(transaccion_tarea=respuesta_parse['TokenAuth']).exists():
            actualizar_estado_tx(respuesta_parse['TokenAuth'], 'Procesando')
        else:
            raise Exception('Task Not Found')
        
        get_task = task_asincrono.objects.using('signgo').get(transaccion_tarea=respuesta_parse['TokenAuth'])
        tarea_asincrona.apply_async(
            args=[respuesta_parse['TokenAuth']], 
            countdown=3,  # ejecutar después de 3 segundos
            retry=True,
            retry_policy={
                'max_retries': 1,
                'interval_start': 0,
                'interval_step': 0.2,
                'interval_max': 0.5,
            },
            task_id = get_task.tx_task
        )
    except Exception as e:
        return JsonResponse({'success': False,'data': f'Falla al guardar tarea asincrona: {e}'})
    return JsonResponse({'success': True,'data': 'Tarea Asincrona Recibida'})

@csrf_exempt
def funcion_ejemplo(request):
    mi_id_personalizado = f"tarea-{uuid.uuid4()}"
    try:    
        tarea_asincrona.apply_async(
            args=[10, 20], 
            countdown=3,  # ejecutar después de 60 segundos
            retry=True,
            retry_policy={
                'max_retries': 1,
                'interval_start': 0,
                'interval_step': 0.2,
                'interval_max': 0.5,
            },
            task_id=mi_id_personalizado
        ) 
    except Exception as e:
        return JsonResponse({'success': False,'data': 'Falla al guardar tarea asincrona'})
    return JsonResponse({'success': True,'data': 'Tarea Asincrona Recibida'})

def actualizar_estado_tx(id, estado):
    try:
        get_task = task_asincrono.objects.using('signgo').get(transaccion_tarea=id)
        get_task.estado = estado
        get_task.save()
    except Exception as e:
        raise Exception(f"Error al actualizar estado: {str(e)}")
    return JsonResponse({'success': True,'data': 'Estado Actualizado'})

