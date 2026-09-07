"""Render the one Cloud Run service definition used by CLI and Cloud Build."""
import json
import os
import sys


def service(env):
    name = env.get('DOCUMENT_OCR_NAME', 'document-ocr')
    profile = env.get('DOCUMENT_OCR_PROFILE', 'economy')
    if profile not in {'economy', 'warm'}:
        raise ValueError('Profile must be economy or warm')
    variables = [{'name': 'DOCUMENT_OCR_KYC_LANGS', 'value': env.get('DOCUMENT_OCR_KYC_LANGS', 'en')}]
    if env.get('GCP_API_TOKEN_SECRET'):
        variables.append({'name': 'API_TOKEN', 'valueFrom': {'secretKeyRef': {
            'name': env['GCP_API_TOKEN_SECRET'], 'key': env.get('GCP_API_TOKEN_VERSION', 'latest')}}})
    return {
        'apiVersion': 'serving.knative.dev/v1', 'kind': 'Service',
        'metadata': {'name': name, 'annotations': {
            'run.googleapis.com/ingress': 'all',
            'run.googleapis.com/invoker-iam-disabled': 'false',
        }},
        'spec': {'template': {
            'metadata': {'annotations': {
                'autoscaling.knative.dev/minScale': '1' if profile == 'warm' else '0',
                'autoscaling.knative.dev/maxScale': env.get('DOCUMENT_OCR_MAX_INSTANCES', '10'),
                'run.googleapis.com/cpu-throttling': 'true',
                'run.googleapis.com/startup-cpu-boost': 'true',
            }},
            'spec': {
                'serviceAccountName': env['DOCUMENT_OCR_SERVICE_ACCOUNT'],
                'containerConcurrency': 1, 'timeoutSeconds': 300,
                'containers': [{
                    'image': env['IMAGE_URI'],
                    'ports': [{'name': 'http1', 'containerPort': 8000}],
                    'resources': {'limits': {'cpu': '2', 'memory': '2Gi'}},
                    'env': variables,
                    'startupProbe': {'httpGet': {'path': '/ready', 'port': 8000}, 'periodSeconds': 5, 'failureThreshold': 30, 'timeoutSeconds': 3},
                    'livenessProbe': {'httpGet': {'path': '/health', 'port': 8000}, 'periodSeconds': 30, 'timeoutSeconds': 3},
                }],
            },
        }},
    }


if __name__ == '__main__':
    json.dump(service(os.environ), sys.stdout, indent=2)
    print()
