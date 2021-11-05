#!/usr/bin/env python3
# -*- coding: utf-8; mode: Python -*-
################################################################################
"""knx_client_script.py -- demo client for UDP-based KNX deployments (ETS) @
Smarthepia

Usage:

    'raw' mode:

        python3 knx_client_script.py [OPTIONS] raw GROUP_ADDRESS PAYLOAD

    'target' mode:

        python3 knx_client_script.py [OPTIONS] TARGET COMMAND ADDRESS [VALUE]


Arguments
=========

'raw' mode
++++++++++

    GROUP_ADDRESS
        <str>. Triple of integers formatted as '<action>/<floor>/<bloc>' in
        [0, 31]/[0, 7]/[0, 255]

    PAYLOAD is a 3-int tuple 'DATA DATA_SIZE APCI':

        DATA
            <int>. Command data in [0, 255]

        SIZE
            <int>. Data size in bytes. Valid range is [1, 2]

        APCI
            <int>. Application Layer Protocol Control Information (service ID)
            command: 0 for group value read (get), or 2 for group value write
            (set)


See L<Deployment configuration> for details.

'target' mode
+++++++++++++

    TARGET
        <str>. Actuator/sensor class in ['blind', 'valve']

    COMMAND
        <str>. Command, depending on chosen target

    ADDRESS
        <str>. Pair of integers formatted as '<floor>/<bloc>' in [0, 7]/[0, 255]

    VALUE
        <int>. Only for command 'set', in percent.


Global options
==============

    -i GATEWAY_IP_ADDRESS
        <str>. Use '127.0.0.1' for a local simulator instance

    -p GATEWAY_UDP_PORT
        <int>. Obvious

    -c CONTROL_ENDPOINT
        <str>. Control endpoint -- use '0.0.0.0:0' with the physycal gateway

    -d DATA_ENDPOINT
        <str>. Data endpoint -- use '0.0.0.0:0' with the physycal gateway

    -l LOG_LEVEL
        <str>. Logging level

Call with '-h' to see help for all options.


Deployment configuration
========================

Legend:

* GADDR = GROUP_ADDRESS ("a/f/b"),
* 'a' = action
* 'f' = floor
* 'b' = bloc
* "don't-care" = any integer

N.B. Action codes in GADDR for blinds and valves are not homogeneous!


Blind's control
+++++++++++++++


action              DATA                SIZE APCI  GADDR  status
----------------------------------------------------------------
full open (set)     0                   1    2     1/f/b  OK
----------------------------------------------------------------
full close (set)    1                   1    2     1/f/b  OK
----------------------------------------------------------------
read state (get)    (don't-care)        1    0     4/f/b  OK
----------------------------------------------------------------
partial open/close  [0...255]           2    2     3/f/b  OK
(set)               0: 100% open
                    255: 100% closed
----------------------------------------------------------------

N.B. Different action codes are used for the various operations.


Valve's control
+++++++++++++++


action              DATA                SIZE APCI  GADDR  status
----------------------------------------------------------------
read state          (don't-care)        1    0     0/f/b  OK
----------------------------------------------------------------
partial open/close  [0...255]           2    2     0/f/b  OK
                    0: 100% closed
                    255: 100% open
----------------------------------------------------------------

N.B. The same action code is used for all the operations.


Examples
========

Raw mode
++++++++

Fully open (set) a blind @ floor 4, bloc 1 (notice a = 1):

  $ python3 knx_client_script.py raw '1/4/1' 0 1 2


Partially close/open [0,255] (set) a blind @ floor 4, bloc 1 (notice a =
3):

  $ python3 knx_client_script.py raw '3/4/1' 100 2 2


Then, read (get) the blind status (notice a = 4, 1234 is used as "don't care"
value):

  $ python3 knx_client_script.py raw '4/4/1' 1234 1 0
  ...
  Result: 100


Target mode
+++++++++++

Fully open a blind @ floor 4, bloc 1:

  $ python3 knx_client_script.py blind open '4/1'


Partially open/close (set 30%) a blind @ floor 4, bloc 1:

  $ python3 knx_client_script.py blind set '4/1' 30


Then, read (get) the blind status:

  $ python3 knx_client_script.py blind get '4/1'
  ...
  Result: 77


Bugs
====

Mostly caused by the fact that SmartHepia deployment is not homogenous.

1. With `actuasim`: a wrong action code might hang the protocol (no final
tunnelling request).

2. Invalid SIZE can crash `actuasim`. Should catch "bad frame" errors.


To-Do
=====

* Clarify control and data endpoints


See Also
========

* Smarthepia Web site L<http://lsds.hesge.ch/smarthepia/>
"""
################################################################################
import argparse, socket, sys, logging
from knxnet import *

logger = None
buf_size = 1024  # bytes

cmmnd_ref = {
    'blind': {
        'get': {
            'data': 1234,  # "don't-care"
            'size': 1,
            'apci': 0,
            'action': 4,
        },
        'set': {
            'data': None,  # from input as 'value'
            'size': 2,
            'apci': 2,
            'action': 3,
        },
        'open': {
            'data': 0,
            'size': 1,
            'apci': 2,
            'action': 1,
        },
        'close': {
            'data': 1,
            'size': 1,
            'apci': 2,
            'action': 1,
        }
    },
    'valve': {
        'get': {
            'data': 1234,  # "don't-care"
            'size': 1,
            'apci': 0,
            'action': 0,
        },
        'set': {
            'data': None,  # from input  as 'value'
            'size': 2,
            'apci': 2,
            'action': 0,
        },
    }
}


################################################################################
def validate_percent_int(string):
    """Scream if input `string` is not an int in [0,100]

    :param str string: the input value to validate

    :returns int: the converted valid input value

    :raises argparse.ArgumentTypeError: when the input is invalid
    """
    value = int(string)
    if value < 0 or value > 100:
        raise argparse.ArgumentTypeError("{}: must be integer in [0, 100]".format(string))

    return value


def build_target_command(target, args):
    """Build a specific "target" command, using the global `cmmnd_ref` dict as a
    reference.

    :param target str: the target command

    :param args namespace: the full argparse namespace

    :returns list:

        str gaddress: the KNX group address

        str payload: the KNX payload

    :raises ValueError: when the a value is not provided for a target called
        with a 'set' command
    """
    logger.debug('args: {}'.format(args))

    if target == 'raw':
        return knxnet.GroupAddress.from_str(args.group_address), args.payload

    # high-level command mode
    cmnd_def = cmmnd_ref[target][args.command]
    logger.debug('cmnd_def: {}'.format(cmnd_def))
    gaddress = knxnet.GroupAddress.from_str(str(cmnd_def['action']) + '/' + args.address)

    payload = [cmnd_def[k] for k in ('data', 'size', 'apci')]
    if args.command == 'set':
        if args.value == None:
            raise ValueError("'set' command requires a 'value'")
        # rescale
        value = int(args.value / 100 * 255)
        # 'set' data
        payload[0] = value

    return gaddress, payload


def send_knx_request(
        dest_group_addr,
        payload,  # data, data_size, apci
        gateway_ip='127.0.0.1', #localhost for the simulator
        gateway_port='3671',    #default for both simulator and real application
        control_endpoint='127.0.0.1:3672',
        data_endpoint='127.0.0.1:3672',
        #control_endpoint=('127.0.0.1',3672),
        #data_endpoint=('127.0.0.1',3672),
        
):
    """Send a request to a KNX gateway for a destination group address with a
    payload.

    Arguments
    +++++++++

    :param dest_group_addr str: group address like 'ACTION/FLOOR/BLOCK'

    :param payload list: a tuple [DATA, DATA_SIZE, APCI]


    Keyword args
    ++++++++++++

    :param gateway_ip str: the gateway's IP address

    :param gateway_port str: the gateway's IP PORT

    :param control_endpoint str: the control endpoint as 'IP-ADDRESS:PORT'

    :param data_endpoint str: the data endpoint as 'IP-ADDRESS:PORT'

    :returns list: (status, reply)

        bool status: success/failure code

        str reply: a numerical value for get commands or a textual status code
            for anything else
    """
    data, data_size, apci = payload

    gateway_port = int(gateway_port)

    control_endpoint = control_endpoint.split(':')
    control_endpoint = tuple([control_endpoint[0], int(control_endpoint[1])])
    data_endpoint = data_endpoint.split(':')
    data_endpoint = tuple([data_endpoint[0], int(data_endpoint[1])])

    local_ip_addr = control_endpoint[0]
    local_udp_port = control_endpoint[1]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('', local_udp_port))

    # -> Connection request (1)
    conn_req = knxnet.create_frame(
        knxnet.ServiceTypeDescriptor.CONNECTION_REQUEST,
        control_endpoint,
        data_endpoint
    )
    logger.debug('>>> CONNECTION_REQUEST:\n{}'.format(conn_req))
    sock.sendto(conn_req.frame, (gateway_ip, gateway_port))

    # <- Connection response (2)
    logger.debug('waiting for a connection response (CONNECTION_RESPONSE -> conn_resp)')
    data_recv, addr = sock.recvfrom(buf_size)
    conn_resp = knxnet.decode_frame(data_recv)
    logger.info('reponse status: {}'.format(conn_resp.status))
    logger.info('reponse data endpoint: {}'.format(conn_resp.data_endpoint))

    ############################################################################
    # @@@ TO BE COMPLETED @@@
    # >>> START OF YOUR WORK

    reader = False
    if not payload[0] and payload[1] and not payload[2]: #yolo
        logger.debug("Payload is read operation")
        reader = True
    else:
        logger.debug("Payload is write operation")
    logger.info('payload: {}'.format(payload))

    # -> Connection state request (3)
    conn_state_req = knxnet.create_frame(
        knxnet.ServiceTypeDescriptor.CONNECTION_STATE_REQUEST,
        conn_resp.channel_id,
        control_endpoint
    )
    logger.debug('>>> CONNECTION_STATE_REQUEST:\n{}'.format(conn_state_req))
    sock.sendto(conn_state_req.frame, (gateway_ip, gateway_port))

    # <- CONNECTION_STATE_RESPONSE (4)
    logger.debug('waiting for a connection state response (CONNECTION_STATE_RESPONSE -> conn_state resp)')
    data_recv, addr = sock.recvfrom(buf_size)
    conn_state_resp = knxnet.decode_frame(data_recv)
    logger.info('status: {}'.format(conn_state_resp.status))

    if conn_state_resp.status == 0x00: #NoError

        # -> TUNNELING_REQUEST (command on/off) (5)
        logger.debug('sending tunneling request (TUNNELING REQUEST -> tunneling request)')
        tunneling_request = knxnet.create_frame(
            knxnet.ServiceTypeDescriptor.TUNNELLING_REQUEST,
            dest_group_addr,
            conn_resp.channel_id,
            data,
            data_size,
            apci,
            0x11    #"Data.request"
        )
        sock.sendto(tunneling_request.frame, (gateway_ip, gateway_port))

        # <- TUNNELLING_ACK_RECEIVED (6)
        logger.debug('Waiting for tunneling ack (TUNNELLING ACK RECEIVED) ...')
        data_recv, addr = sock.recvfrom(buf_size)
        tunneling_resp_ack = knxnet.decode_frame(data_recv)
        logger.debug('TUNNELLING ACK RECEIVED -> tunneling_resp_ack ')
        logger.info('status: {}'.format(tunneling_resp_ack.status))

        if tunneling_resp_ack.status == 0x00: #NoError

            # <- TUNNELLING_REQUEST_RECEIVED (7)
            logger.debug('Waiting for tunneling request confirmation (TUNNELING CONFIRMATION RECEIVED) ...')
            data_recv, addr = sock.recvfrom(buf_size)
            tunneling_conf_request = knxnet.decode_frame(data_recv)
            logger.debug('tunneling request confirmation received (TUNNELING CONFIRMATION RECEIVED -> tunneling_conf_request)')

            if tunneling_conf_request.data_service == 0x2e: #Data.confirmation

                # -> TUNNELLING_ACK (8)
                logger.debug('sending tunneling ack (TUNNELING ACK -> tunneling ack)')
                tunneling_ack = knxnet.create_frame(
                    knxnet.ServiceTypeDescriptor.TUNNELLING_ACK,
                    conn_resp.channel_id,
                    #tunneling_resp_ack.statut,
                    tunneling_conf_request.sequence_counter
                )
                sock.sendto(tunneling_ack.frame, (gateway_ip, gateway_port))

                if reader: #Read command #THERE IS NO 3RD TUNNELING REQUEST ON WRITINGS
                    # <- TUNNELLING_REQUEST_RECEIVED (9) 
                    logger.debug('SINCE READ Waiting: for tunneling request response (TUNNELING RESPONSE RECEIVED) ...')
                    data_recv, addr = sock.recvfrom(buf_size)
                    tunneling_resp_request = knxnet.decode_frame(data_recv)
                    logger.debug('tunneling request response received (TUNNELING RESPONSE RECEIVED -> tunneling_resp_request)')                 

                # -> DISCONNECT_REQUEST
                logger.debug('sending disconnect request (DISCONNECT REQUEST -> discon_request)')
                discon_request = knxnet.create_frame(
                    knxnet.ServiceTypeDescriptor.DISCONNECT_REQUEST,
                    conn_resp.channel_id,
                    control_endpoint
                )
                logger.debug('>>> DISCONNECT_REQUEST:\n{}'.format(discon_request))
                sock.sendto(discon_request.frame, (gateway_ip, gateway_port))

                # <- DISCONNECT_RESPOND
                logger.debug('waiting for disconnection response (DISCONNECT_RESPOND)... ')
                data_recv, addr = sock.recvfrom(buf_size)
                discon_resp = knxnet.decode_frame(data_recv)
                logger.debug('disconnection response received (DISCONNECT_RESPOND -> discon_resp)')

                """ #No attribute 'status'
                if discon_resp.status == 0x00:
                    print('Fin du traitement')
                """

                if reader:
                    return True, tunneling_resp_request.data
                else:
                    return True, 'Success'
        else:
            logger.debug('Tunnelling ack error : {}'.format(tunneling_resp_ack.status))

    else:
        logger.info('Connexion state response error: {}'.format(conn_state_resp.status))
    ############################################################################

    # So far, only the first 2 steps of a full
    # protocol round were done (CONNECTION_REQUEST/RESPONSE).  Keep in mind
    # that:

    # you have to ckeck status codes to see if the the command was correctly
    # understood, and _disconnect_ otherwise (DISCONNECT_REQUEST). Then again
    # check if that went through;

    # the `acpi` tells you if you're handling a get (read) or a set (write)
    # command.

    # <<< END OF YOUR WORK
    ############################################################################

    return False, 'Error'


################################################################################
if __name__ == "__main__":
    logging.basicConfig(
        # level=logging.WARNING,
        format='%(levelname)-8s %(message)s'
    )
    logger = logging.getLogger('knx_client')

    ############################################################################
    # main parser
    ############################################################################
    parser = argparse.ArgumentParser(
        description='Demo client for UDP-based KNX deployments (ETS) @ Smarthepia',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '-m', '--manual',
        dest='manual',
        action='store_true',
        help='print the full documentation'
    )

    parser.add_argument(
        '-i', '--gateway-ip-address',
        dest='gateway_ip_address',
        type=str,
        default='127.0.0.1',
        help="Gateway's IP address"
    )

    parser.add_argument(
        '-p', '--gateway-udp-port',
        dest='gateway_udp_port',
        type=str,
        default='3671',
        help="Gateway's UDP port"
    )

    parser.add_argument(
        '-c', '--control-endpoint',
        dest='control_endpoint',
        type=str,
        default='127.0.0.1:3672',
        help="Control endpoint -- use '0.0.0.0:0' for NAT"
    )

    parser.add_argument(
        '-d', '--data-endpoint',
        dest='data_endpoint',
        type=str,
        default='127.0.0.1:3672',
        help="Data endpoint -- use '0.0.0.0:0' for NAT"
    )

    parser.add_argument(
        '-l', '--log-level',
        dest='log_level',
        type=str,
        default='ERROR',
        choices=(
            'CRITICAL',
            'ERROR',
            'WARNING',
            'INFO',
            'DEBUG',
        ),
        help="Logging level"
    )

    ############################################################################
    # subcommands
    ############################################################################
    subparsers = parser.add_subparsers(
        title='targets',
        dest='subparser_name',
        help='Target actuator/sensor ("raw" is for low-level KNX-style)'
    )

    # @raw target
    parser_raw = subparsers.add_parser(
        'raw',
        help='send low-level KNX-style commands, such as "-g ACTION/FLOOR/BLOCK DATA SIZE ACPI"',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser_raw.add_argument(
        'group_address',
        type=str,
        help='KNX group address "<action>/<floor>/<bloc>"'
    )

    parser_raw.add_argument(
        'payload',
        # no metavar, else choices won't be proposed on -h
        type=int,
        nargs=3,
        help="3-int tuple 'DATA DATA_SIZE APCI'"
    )

    # @blind target
    parser_blind = subparsers.add_parser(
        'blind',
        help='send high-level commands to blinds, such as "get FLOOR/BLOCK"',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser_blind.add_argument(
        'command',
        type=str,
        choices=('open', 'close', 'get', 'set'),
        help='Blind command (get == read, set == write)'
    )

    parser_blind.add_argument(
        'address',
        type=str,
        help='Blind address "<floor>/<bloc>"'
    )

    parser_blind.add_argument(
        'value',
        nargs='?',
        type=validate_percent_int,
        help='Set value percent [0, 100]'
    )

    # @valve target
    parser_valve = subparsers.add_parser(
        'valve',
        help='send high-level commands to valves, such as "get FLOOR/BLOCK"',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser_valve.add_argument(
        'command',
        type=str,
        choices=('get', 'set'),
        help='Valve command (get == read, set == write)'
    )

    parser_valve.add_argument(
        'address',
        type=str,
        help='Valve address "<floor>/<bloc>"'
    )

    parser_valve.add_argument(
        'value',
        nargs='?',
        type=validate_percent_int,
        help='Set value percent [0,100]'
    )

    ############################################################################

    args = parser.parse_args()

    if args.manual:
        print(__doc__)
        sys.exit(0)

    logger.debug("target: {}".format(args.subparser_name))
    target = args.subparser_name
    if not target:
        parser.print_usage()
        sys.exit('\nPlease provide a "target"')

    logger.setLevel(args.log_level)

    # parse high-level command
    try:
        dest_addr, payload = build_target_command(target, args)
    except ValueError as e:
        sys.exit("Can't build target command: {}".format(e))

    logger.info(
        'going to send command: {} (group address) {} (payload)'.format(dest_addr, payload)
    )

    reply = send_knx_request(
        dest_addr,
        payload,
        gateway_ip=args.gateway_ip_address,
        gateway_port=args.gateway_udp_port,
        control_endpoint=args.control_endpoint,
        data_endpoint=args.data_endpoint,
    )

    logger.debug('reply: {}'.format(reply))

    status = 0 if reply[0] else 1
    result = reply[1]
    try:
        result = int(result)
        result = '{} ({}%)'.format(result, int(result / 255 * 100))
    except ValueError:
        pass

    print('Result: {}'.format(result))

    sys.exit(status)
