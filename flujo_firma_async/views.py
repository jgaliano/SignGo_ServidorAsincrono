from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
import uuid
import json
from django.http import HttpResponse, JsonResponse
from .tasks import tarea_asincrona_flujo_firma
from flujo_firma_async.flujo_firma_models import task_asincronoFlujo

# Create your views here.
def helloworld(request):
    return render(request, 'helloworld.html')

@csrf_exempt
def tarea_async(request):
    mi_id_personalizado = f"tarea-{uuid.uuid4()}"
    try:
        respuesta_parse = json.loads(request.body)
        if task_asincronoFlujo.objects.using('signgo').filter(transaccion_tarea=respuesta_parse['TokenAuth']).exists():
            actualizar_estado_tx(respuesta_parse['TokenAuth'], 'Procesando')
        else:
            raise Exception('Task Not Found')
        
        get_task = task_asincronoFlujo.objects.using('signgo').get(transaccion_tarea=respuesta_parse['TokenAuth'])
        tarea_asincrona_flujo_firma.apply_async(
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


def actualizar_estado_tx(id, estado):
    try:
        get_task = task_asincronoFlujo.objects.using('signgo').get(transaccion_tarea=id)
        get_task.estado = estado
        get_task.save()
    except Exception as e:
        raise Exception(f"Error al actualizar estado: {str(e)}")
    return JsonResponse({'success': True,'data': 'Estado Actualizado'})
