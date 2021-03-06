# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
#
# Copyright (c) 2020 ScyllaDB

from sdcm.db_stats import PrometheusDBStats


def avg(values):
    if values:
        return float(format(sum([float(val) for val in values])/len(values), '.1f'))
    else:
        return None


def collect_latency(monitor_node, start, end, load_type, cluster, nodes_list):
    res = dict()
    prometheus = PrometheusDBStats(host=monitor_node.ip_address)
    duration = int(end - start)
    cassandra_stress_precision = ['99', '95']  # in the future should include also 'max'
    scylla_precision = ['99']  # in the future should include also '95', '5'

    for precision in cassandra_stress_precision:
        metric = f'c-s {precision}' if precision == 'max' else f'c-s P{precision}'
        if not precision == 'max':
            precision = f'perc_{precision}'
        query = f'collectd_cassandra_stress_{load_type}_gauge{{type="lat_{precision}"}}'
        query_res = prometheus.query(query, start, end)
        latency_values_lst = list()
        for entry in query_res:
            lat_value = None
            if not entry['values']:
                continue
            sequence = [val[-1] for val in entry['values'] if not val[-1].lower() == 'nan']
            if all([val == sequence[0] for val in sequence]):
                continue
            if precision == 'max':
                if sequence:
                    lat_value = max([float(val) for val in sequence])
            else:
                lat_value = avg(sequence)
            latency_values_lst.append(lat_value)
        if latency_values_lst:
            res[metric] = format(float(max([float(val) for val in latency_values_lst])), '.2f') if precision == 'max' \
                else format(float(avg(latency_values_lst)), '.2f')

    for precision in scylla_precision:
        query = f'histogram_quantile(0.{precision},sum(rate(scylla_storage_proxy_coordinator_{load_type}_' \
                f'latency_bucket{{}}[{duration}s])) by (instance, le))'
        query_res = prometheus.query(query, start, end)
        for entry in query_res:
            node_ip = entry['metric']['instance'].replace('[', '').replace(']', '')
            node = cluster.get_node_by_ip(node_ip)
            if not node:
                for db_node in nodes_list:
                    if db_node.ip_address == node_ip:
                        node = db_node
            if node:
                node_idx = node.name.split('-')[-1]
            else:
                continue
            node_name = f'node-{node_idx}'
            metric = f"Scylla P{precision} - {node_name}"
            if not entry['values']:
                continue
            sequence = [val[-1] for val in entry['values'] if not val[-1].lower() == 'nan']
            if sequence:
                res[metric] = format(float(avg(sequence) / 1000), '.2f')

    return res


def calculate_latency(latency_results):
    result_dict = dict()
    for workload in latency_results.keys():
        if workload not in result_dict:
            result_dict[workload] = dict()
        all_keys = list(latency_results[workload].keys())
        steady_key = ''
        if all_keys:
            steady_key = [key for key in all_keys if 'steady' in key.lower()]
        if not steady_key or not all_keys:
            result_dict[workload] = latency_results[workload]
            continue
        else:
            steady_key = all_keys.pop(all_keys.index(steady_key[0]))
        result_dict[workload][steady_key] = latency_results[workload][steady_key].copy()
        for key in all_keys:
            result_dict[workload][key] = latency_results[workload][key].copy()
            temp_dict = dict()
            for cycle in latency_results[workload][key]['cycles']:
                for metric, value in cycle.items():
                    if metric not in temp_dict:
                        temp_dict[metric] = list()
                    temp_dict[metric].append(value)
            for temp_key, temp_val in temp_dict.items():
                if 'Cycles Average' not in result_dict[workload][key]:
                    result_dict[workload][key]['Cycles Average'] = dict()
                average = format(float(avg(temp_val)), '.2f')
                result_dict[workload][key]['Cycles Average'][temp_key] = float(f'{average}')
                if 'Relative to Steady' not in result_dict[workload][key]:
                    result_dict[workload][key]['Relative to Steady'] = dict()
                if temp_key in latency_results[workload][steady_key]:
                    steady_val = float(latency_results[workload][steady_key][temp_key])
                    if steady_val != 0:
                        result_dict[workload][key]['Relative to Steady'][temp_key] = \
                            format((float(average) - steady_val), '.2f')

    return result_dict
