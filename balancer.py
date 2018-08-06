#!/usr/bin/python3

import requests
import subprocess
import json
import time
import sys
import os
import configparser
import logging

# For more information about prometheus metrices see:
# https://github.com/dashpole/cadvisor/blob/1dcd0cee2b05590a8b5515f5c41a80905d2fc1c2/metrics/prometheus.go

_ROOT = os.path.abspath(os.path.dirname(__file__))
CFG = configparser.ConfigParser()
CFG.read(os.path.join(_ROOT, 'balancer.cfg'))
verbosity = 2

logger = logging.getLogger('balancer')
ch = logging.StreamHandler()
logger.addHandler(ch)
logger.setLevel(logging.NOTSET)
if verbosity == 1:
    logger.setLevel(logging.WARNING)
if verbosity == 2:
    logger.setLevel(logging.INFO)
if verbosity == 3:
    logger.setLevel(logging.DEBUG)

def result_to_int(result_str):
    """Parse result received by prometheus query and return rounded value as int or 0."""
    if result_str:
        result_int = int(result_str.split('.')[0])
        return result_int
    return 0

def send_request(query_string, prometheus_url):
    """Send a request to the Prometheus API and return the response or None."""
    try:
        response = requests.get(
            url=prometheus_url,
            params={
                "query": query_string,
            },
        )
        logger.debug('Response HTTP Status Code: {status_code}'.format(
            status_code=response.status_code))
        logger.debug('Response HTTP Response Body: {content}'.format(
            content=response.content))
    except requests.exceptions.RequestException:
        logger.warning('HTTP Request failed')
        raise

    # https://stackoverflow.com/questions/40059654/python-convert-a-bytes-array-into-json-format
    bytes_value = response.content
    bytes_to_str = bytes_value.decode('utf8').replace("'", '"')
    response_parsed = json.loads(bytes_to_str)
    try:
        result = response_parsed['data']['result'][0]['value'][1]
    except IndexError:
        # Prometheus returned empty response for this query
        result = None

    return result


def get_traffic_received(image, interval, prometheus_url):
    """Query Prometheus API for network traffic information.
    Return received and sent traffic size for a given interval or None.

    eg: sum(rate(container_network_receive_bytes_total{image="networkstatic/iperf3"}[10m]))
    """
    query_string = "sum(rate(container_network_receive_bytes_total{{image=\"{}\"}}[{}]))".format(
        image, interval)
    result = send_request(query_string, prometheus_url)
    result = result_to_int(result)
    logger.info('Traffic received for image {}: {}.'.format(image, result))
    return result


def get_traffic_sent(image, interval, prometheus_url):
    """Query Prometheus API for network traffic information.
    Return received and sent traffic size for a given interval or None.

    Eg.: sum(rate(container_network_transmit_bytes_total{image="networkstatic/iperf3"}[10m]))
    """
    query_string = "sum(rate(container_network_transmit_bytes_total{{image=\"{}\"}}[{}]))".format(
        image, interval)
    result = send_request(query_string, prometheus_url)
    result = result_to_int(result)
    logger.info('Traffic sent for image {}: {}.'.format(image, result))
    return result


def get_cpu_usage(image, interval, prometheus_url):
    """Query Prometheus API for cpu usage information.
    Return usage for a given interval or None.

    Eg.: sum(rate(process_cpu_seconds_total{image="networkstatic/iperf3"}[10m]))
    """
    query_string = "sum(rate(process_cpu_seconds_total{{image=\"{}\"}}[{}]))".format(
        image, interval)
    result = send_request(query_string, prometheus_url)
    result = result_to_int(result)
    logger.info('CPU usage for image {}: {}.'.format(image, result))
    return result


def get_memory_usage(image, interval, prometheus_url):
    """Query Prometheus API for memory usage information.
    Return usage for a given interval or None.

    Eg.: sum(rate(container_memory_usage_bytes{image="networkstatic/iperf3"}[10m]))
    """
    query_string = "sum(rate(container_memory_usage_bytes{{image=\"{}\"}}[{}]))".format(
        image, interval)
    result = send_request(query_string, prometheus_url)
    result = result_to_int(result)
    logger.info('Memory usage for image {}: {}.'.format(image, result))
    return result


def get_scale_to(section, traffic_received, traffic_sent, memory_used, cpu_used, size_current):
    """Parse traffic, cpu and memory usage depending on the number of instances
    (size) and return a touple if scaling should occure and if so to what size.
    """

    scaling_should_occure = False
    size_difference = 0

    traffic_received = (traffic_received/size_current)/size_current
    traffic_sent = (traffic_sent/size_current)/size_current
    memory_used = (memory_used/size_current)/size_current
    cpu_used = (cpu_used/size_current)/size_current

    # Scale out
    if traffic_received > int(CFG[section]['traffic_received_limit_upper']):
        size_difference += 1
    if traffic_sent > int(CFG[section]['traffic_sent_limit_upper']):
        size_difference += 1
    if memory_used > int(CFG[section]['memory_used_limit_upper']):
        size_difference += 1
    if cpu_used > int(CFG[section]['cpu_used_limit_upper']):
        size_difference += 1

    # Scale in
    if traffic_received < int(CFG[section]['traffic_received_limit_lower']):
        size_difference -= 1
    if traffic_sent < int(CFG[section]['traffic_sent_limit_lower']):
        size_difference -= 1
    if memory_used < int(CFG[section]['memory_used_limit_lower']):
        size_difference -= 1
    if cpu_used < int(CFG[section]['cpu_used_limit_lower']):
        size_difference -= 1

    # Always scale out for testing
    # size_difference = 1

    size_ideal = size_current + size_difference
    if size_ideal > int(CFG[section]['size_max']):
        size_ideal = int(CFG[section]['size_max'])
    if size_ideal < int(CFG[section]['size_min']):
        size_ideal = int(CFG[section]['size_min'])
    if size_ideal != size_current:
        scaling_should_occure = True
    if int(CFG[section]['scale_service']) == 0:
        scaling_should_occure = False


    logger.info('Ideal size for {} is {}.'.format(section, size_ideal))
    return scaling_should_occure, size_ideal


def scale_service(service, size_ideal):
    """Call docker-compose to scale the service in
    question to the appropriate size.
    Return docker-compose exit code.
    """
    cmd = ['docker-compose',
           'up',
           '--detach',
           '--scale',
           '{}={}'.format(service, size_ideal)]
    logger.debug(cmd)
    proc = subprocess.Popen(cmd,
                            bufsize=-1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    rc = proc.returncode
    if rc != 0:
        logger.warning('Error while scaling service {} to size {}.'.format(
            service, size_ideal))
        stop_epc()
        sys.exit(err.decode('utf8'))
    return rc


def start_epc():
    """Run docker-compose in detach mode to start
    the dockerized EPC.
    Must be started with the root of our EPC repo
    as working directory in order for the docker-
    compose file to be found.
    """
    cmd = ['docker-compose',
           'up',
           '--detach']
    proc = subprocess.Popen(cmd,
                            bufsize=-1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    rc = proc.returncode
    if rc != 0:
        logger.warning('Error while starting docker containers. Stopping running instances')
        stop_epc()
        sys.exit(err.decode('utf8'))
    logger.warning('Container(s) started')
    logger.warning(err.decode('utf8'))
    return rc


def stop_epc():
    """Run docker-compose to stop funning containers.
    Same restrictions as for start_epc apply."""
    proc = subprocess.Popen(['docker-compose', 'stop'],
                            bufsize=-1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    rc = proc.returncode
    if rc != 0:
        logger.warning('Error while shutting down instances.')
        sys.exit(err.decode('utf8'))
    logger.warning('Container(s) stopped')
    logger.warning(err.decode('utf8'))
    return rc


def reload_loadbalancer(container_name):
    """Reload nginx inside docker container. Return exit code of subprocess."""
    cmd = ['docker', 'container', 'exec', container_name, 'nginx', '-s',
           'reload', ]
    proc = subprocess.Popen(
        cmd, bufsize=-1, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    rc = proc.returncode
    if rc != 0:
        logger.warning('Error reloading nginx.')
    return rc


def balance(section):
    """Run our balancer logic"""
    service = CFG[section]['service']
    logger.info('Balance service {}'.format(service))
    traffic_received = get_traffic_received(CFG[section]['docker_image'], CFG[section]['interval'], CFG[section]['prometheus_url'])
    traffic_sent = get_traffic_sent(CFG[section]['docker_image'], CFG[section]['interval'], CFG[section]['prometheus_url'])
    memory_used = get_memory_usage(CFG[section]['docker_image'], CFG[section]['interval'], CFG[section]['prometheus_url'])
    cpu_used = get_cpu_usage(CFG[section]['docker_image'], CFG[section]['interval'], CFG[section]['prometheus_url'])
    scaling_should_occure, size_ideal = get_scale_to(
        section, traffic_received, traffic_sent, memory_used, cpu_used, int(CFG[section]['size_current']))

    # Update cooldown timer
    timer = int(CFG[section]['cool_down_timer'])
    if timer > 0:
        timer -= 1
        CFG[section]['cool_down_timer'] = str(timer)

    if scaling_should_occure:
        if timer > 0:
            logger.debug("Timer is {}. Not scaling.".format(timer))
            return str(int(CFG[section]['size_current']))

        logger.info('Ideal size is {}, current is {}. Scaling service {}.'.format(size_ideal, int(CFG[section]['size_current']), service))
        rc = scale_service(service, size_ideal)
        if rc != 0:
            logger.warning('Error: Could not scale service {} to size {}.'.format(
                service, size_ideal))
            return str(int(CFG[section]['size_current']))

        CFG[section]['cool_down_timer'] = CFG[section]['cool_down_timer_max']
        CFG[section]['size_current'] = str(size_ideal)
        logger.info('Service {} scaled to {}.'.format(service, int(CFG[section]['size_current'])))
        reload_loadbalancer(CFG[section]['load_balancer'])
    return str(int(CFG[section]['size_current']))


if __name__ == '__main__':
    """Start dockerized EPC and continue to
    query the prometheus API
    """
    try:
        start_epc()
        time.sleep(int(CFG[CFG.sections()[0]]['wait_time']))
        while True:
            time.sleep(int(CFG[CFG.sections()[0]]['wait_time']))
            for section in CFG.sections():
                CFG[section]['size_current'] = balance(section)
    except KeyboardInterrupt:
        logger.warning('\nShutting down...')
        stop_epc()
    except:
        stop_epc()
        raise
