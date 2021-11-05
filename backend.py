# -*- coding: utf-8; mode: python -*-
################################################################################
"""backend.py -- a Flask-based server for HEPIA's LSDS Smart Building IoT
Z-Wave Lab (backend)

Documentation is written in `apidoc <http://www.python.org/>`_. You should
already have a copy in `doc/index.html`

To-do
=====

[-] See how to extract/convert apidoc comments with `pydoc`. Later.
[-] Any way of explicitly probing the physical layer (via underlying lib) via
  signals instead of polling? Later.
[~] Document all methods -- sphynx-style
[~] Add test harness, units and doctests.

Next milestones:

[ ] Monolithic backend architecture is inflexible: modularize into components
    (nodes) with specific classes.
[ ] Unify [g/s]etter methods for nodes via properties .


Bugs
====

* Why a global `started`? Network status flags should be object attributes
  propbed via properties.

* Not thread-safe because of pseudo-monitor code over node_added flags and
  possibly other ugly kludges.

* DO NOT TRUST OZW's notification system: notification handlers are not
  guaranteed atomic execution... Who's to blame? Race condition somewhere?

"""
################################################################################
import os, sys, time, logging, configpi, re, warnings
import six
if six.PY3:
    from pydispatch import dispatcher
else:
    from louie import dispatcher
# from louie import dispatcher
from datetime import datetime
from flask import jsonify
from collections import OrderedDict
from openzwave.network import ZWaveNetwork
from openzwave.option import ZWaveOption


################################################################################
# globals
################################################################################

started = False

################################################################################
# functions
################################################################################

def _tstamp_label(node):
    """Make a timestamp label for a node out of its ID.

    :param object node: a :class:`openzwave.node`

    :returns: string: 'timestamp<NID>'
    """
    return "timestamp" + str(node.node_id)

def _node_label(node):
    """Make a node label for a node out of its ID.

    :param object node: a :class:`openzwave.node`

    :returns: string: 'Node <NID>'
    """
    return "Node{:>03}".format(node.node_id)

def json_prepare(data):
    """Prepare `data` for JSON serialization by converting:

        set => tuple
        ...

    :param obj data: an OZW :class:`ZWaveValue` object

    :returns: dict: data as a JSON-serializable dict
    """
    return dict(
        map(
            lambda i: (i[0], tuple(i[1]) if type(i[1]) is set else i[1]),
            data.to_dict().items()
        )
    )

def f_to_c(temperature):
    return (temperature - 32)*5/9


################################################################################
################################################################################

class Backend():
    """Root parent backend class
    """
    CONTROLLER_NODE_ID = 1

    logger = None
    network = None

    _labels_xref = {
        # us => OZW
        'battery'     : 'Battery Level',
        'burglar'     : 'Burglar',
        'humidity'    : 'Relative Humidity',
        'level'       : 'Level',
        'luminance'   : 'Luminance',
        'motion'      : 'Sensor',
        'temperature' : 'Temperature',
        'ultraviolet' : 'Ultraviolet',
    }

    _initials = {
        # all optional... These are used asr args for __init__()
        # public
        'device'                        : configpi.device,
        'ozw_config_path'               : configpi.config_path,
        'ozw_user_path'                 : configpi.user_path,
        'log_level'                     : configpi.log_level,
        'log_format'                    : configpi.log_format,
        'log_format_dbg'                : configpi.log_format_dbg,
        're_dimmer'                     : configpi.re_dimmer,
        're_sensor'                     : configpi.re_sensor,
        'controller_name'               : configpi.name,
        'network_ready_timeout'         : configpi.network_ready_timeout,
        'controller_operation_timeout'  : configpi.controller_operation_timeout,
    }

    _initialized = False
    def __init__(self, **kwargs):
        """Attrs initialized here have names as in :dict:`_initials`

        Doctests
        ++++++++

        >>> t.start()
        (True, 'OK')

        # >>> t.hard_reset(force=True)
        # (True, 'OK')
        # >>> print("*** Action needed for node to be _added_ ***") # doctest:+ELLIPSIS
        # *** ...
        # >>> t.add_node() # doctest:+ELLIPSIS
        # {...}
        """
        if self._initialized:
            raise RuntimeErr("[Bug] backend already initialized!?")

        self._initialized = True

        # set defaults
        for attr in self._initials.keys():
            setattr(self, attr, self._initials[attr])

        # ...remainder.
        for k in kwargs.keys():
            if not hasattr(self, k):
                raise AttributeError(
                    "{}: no such attribute in definition of class {}.".format(
                        k, self.__class__.__name__
                    )
                )
            else:
                setattr(self, k, kwargs[k])

        # we put all artifacts here
        user_path = os.path.expanduser(
            os.path.expandvars(self.ozw_user_path)
        )
        try:
            os.makedirs(self.ozw_user_path, exist_ok=True)
        except Exception as e:
            raise RuntimeError("Can't create user_path: {}".format(e))


        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(self.log_level)


        fh = logging.FileHandler(
            "{}/{}.log".format(self.ozw_user_path, __name__), mode='w'
        )
        fh.setLevel(self.log_level)
        fh.setFormatter(
            logging.Formatter(
                self.log_format_dbg if self.log_level <= logging.DEBUG else self.log_format
            )
        )
        self.logger.addHandler(fh)

        self.logger.debug('initializing OZW backend...')

        options = ZWaveOption(
            self.device,
            config_path=self.ozw_config_path,
            user_path=self.ozw_user_path
        )

        options.set_log_file('OZW.log')
        options.set_append_log_file(False)
        options.set_console_output(False)
        options.set_save_log_level(
            'Debug' if self.log_level <= logging.DEBUG else 'Warning'
        )
        options.set_logging(True)
        options.lock()

        self.network = ZWaveNetwork(options, autostart=False)

        # A dispatcher associates a callback method to a signal. Signals
        # are generated by the library python-openzwave. Once a signal is
        # received, its associated callback is executed (see "_node_added"
        # example below in "_network_started" method)
        dispatcher.connect(self._network_started, ZWaveNetwork.SIGNAL_NETWORK_STARTED)
        dispatcher.connect(self._network_ready, ZWaveNetwork.SIGNAL_NETWORK_READY)
        # Yep! It's really 'RESETTED', wanna file a bug for bad english usage? ;-)
        dispatcher.connect(self._network_reset, ZWaveNetwork.SIGNAL_NETWORK_RESETTED)

        # dynamically set on add/remove events. See notification handlers below.
        self.node_added = None
        self.node_removed = None
        self.timestamps = {}              # times of the last values' update for each sensor

        # The different stages that a node object gets through before being
        # ready. [BUG] Why do we need to explicitly list them? Anyway to get
        # them from the lib?
        self.queryStages = {
            "None"                  :  1, # Query process hasn't started for this node
            "ProtocolInfo"          :  2, # Retrieve protocol information
            "Probe"                 :  3, # Ping node to see if alive
            "WakeUp"                :  4, # Start wake up process if a sleeping node
            "ManufacturerSpecific1" :  5, # Retrieve manufacturer name and product ids if ProtocolInfo lets us
            "NodeInfo"              :  6, # Retrieve info about supported, controlled command classes
            "SecurityReport"        :  7, # Retrieve a list of Command Classes that require Security
            "ManufacturerSpecific2" :  8, # Retrieve manufacturer name and product ids
            "Versions"              :  9, # Retrieve version information
            "Instances"             : 10, # Retrieve information about multiple command class instances
            "Static"                : 11, # Retrieve static information (doesn't change)
            "Probe1"                : 12, # Ping a node upon starting with configuration
            "Associations"          : 13, # Retrieve information about associations
            "Neighbors"             : 14, # Retrieve node neighbor list
            "Session"               : 15, # Retrieve session information (changes infrequently)
            "Dynamic"               : 16, # Retrieve dynamic information (changes frequently)
            "Configuration"         : 17, # Retrieve configurable parameter information (only done on request)
            "Complete"              : 18  # Query process is completed for this node
        }


    def _is_network_started(self):
        """Check if self.network is started. See <http://openzwave.github.io/python-openzwave/network.html?highlight=state#openzwave.network.ZWaveNetwork.state>

        :returns: bool
        """
        return self.network.state >= self.network.STATE_STARTED


    def _lookup_node(self, nid):
        """Look up a node in `self.network.nodes` by its ID.

        :param int nid: the wanted node's ID

        :returns: object: a :class:`openzwave.node` or None if the wanted node
                is not found
        """
        self.logger.debug("nodes: {}".format(self.network.nodes))
        return next(
            # index i is discarded
            (node for i, node in self.network.nodes.items() if node.node_id == nid),
            None # default
        )


    def _lookup_sensor_node(self, nid):
        """Look up a sensor node in `self.network.nodes` by its ID.

        :param int nid: the wanted node's ID

        :returns: object: a :class:`openzwave.node` or None if the wanted node
                is not found

        :raises: RuntimeError: if the node is not {found | ready | sensor}
        """
        node = self._lookup_node(nid)

        if not node:
            raise RuntimeError("No such node")

        if not (node.is_ready or self._has_timestamp(node)):
            raise RuntimeError("Not ready")

        if not self._is_sensor(node):
            raise RuntimeError("Not a sensor")

        return node


    def _lookup_dimmer_node(self, nid):
        """Look up a dimmer node in `self.network.nodes` by its ID.

        :param int nid: the wanted node's ID

        :returns: object: a :class:`openzwave.node` or None if the wanted node
                is not found

        :raises: RuntimeError: if the node is not {found | ready | dimmer}
        """
        node = self._lookup_node(nid)

        if not node:
            raise RuntimeError("No such node")

        if not (node.is_ready or self._has_timestamp(node)):
            raise RuntimeError("Not ready")

        if not self._is_dimmer(node):
            raise RuntimeError("Not a dimmer")

        return node


    def _network_reset(self, network):
        """Callback executed when the controller is hard reset.

        :returns: None
        """
        self.logger.info(
            "Network hard reset: home ID {:08x}, {} nodes found".format(
                network.home_id, network.nodes_count
            )
        )

    def _network_started(self, network):
        """Callback executed once the OZW network is _started_ (SIGNAL_NETWORK_STARTED
        is raised). The discovery of the network components has begun: they
        will be mapped into objects.

        WARNING! No guarantee of atomic execution. Avoid ANY I/O here (I'm
        looking at you, logger), unless it's the _last_ statement executed...

        :returns: None
        """
        self.logger.info(
            "Network started: home ID {:08x}, {} nodes found".format(
                network.home_id, network.nodes_count
            )
        )


    def _network_ready(self, network):
        """Callback executed once the OZW network is ready for opertion
        (SIGNAL_NETWORK_READY is raised).

        WARNING! No guarantee of atomic execution. Avoid ANY I/O here (I'm
        looking at you, logger), unless it's the _last_ statement executed...

        :returns: None
        """
        dispatcher.connect(self._node_added, ZWaveNetwork.SIGNAL_NODE_ADDED)
        dispatcher.connect(self._node_removed, ZWaveNetwork.SIGNAL_NODE_REMOVED)
        dispatcher.connect(self._value_update, ZWaveNetwork.SIGNAL_VALUE)


    def _node_added(self, network, node):
        """Callback executed when a node is added to the network (signal
        SIGNAL_NODE_ADDED is raised). On execution, `self.node_added` is set
        to the newly added node, an :class:`openzwave.node` obect.

        WARNING! No guarantee of atomic execution. Avoid ANY I/O here (I'm
        looking at you, logger), unless it's the _last_ statement executed...

        :returns: None
        """
        self.node_added = node
        self._set_node_timestamp(node, None)
        self.logger.info('node added: {}'.format(node.node_id))


    def _node_removed(self, network, node):
        """Callback executed when node is removed from the network (signal
        SIGNAL_NODE_REMOVED is raised). On execution, `self.node_removed` is set
        with the removed node, an :class:`openzwave.node` obect.

        WARNING! No guarantee of atomic execution. Avoid ANY I/O here (I'm
        looking at you, logger), unless it's the _last_ statement executed...

        :returns: None
        """
        self.node_removed = node
        self.timestamps.pop(_tstamp_label(node), None)
        self._del_node_timestamp(node)
        self.logger.info('node removed: {}'.format(node.node_id))


    def _value_update(self, network, node, value):
        """Callback executed whenever a node's reading value is changed, added,
        removed, etc. Node's timestamp is also updated.

        WARNING! No guarantee of atomic execution. Avoid ANY I/O here (I'm
        looking at you, logger), unless it's the _last_ statement executed...

        :returns: None        """
        self._set_node_timestamp(node, int(time.time()))
        self.logger.debug("timestamp: {}".format(self.get_node_timestamp(node)))


    ############################################################################
    # @network
    ############################################################################
    def start(self):
        """Start the software representation. It won't restart an already started
        network -- use `reset()` instead.

        :returns: tuple(bool, string): (status, reason) where:

                status: True on success, False if the network was already start
                reason: a textual explanation
        """
        global started

        if started:
            msg = "System already started. Skipping..."
            self.logger.warning(msg)
            return (False, msg)

        self.network.start()

        self.logger.info(
            "Z-Wave Network Starting -- timeout in {}s. Please wait...".format(
                self.network_ready_timeout
            )
        )

        # [BUG] why this f***in polling? Must file an RFE for a callback-based
        # notification
        timeout = True
        for i in range(0, self.network_ready_timeout):
            if self.network.is_ready:
                self.logger.debug("Network ready after {}s".format(i))
                timeout = False
                break
            else:
                time.sleep(1.0)

        if not self.network.is_ready:
            self.logger.warning(
                (
                    "Network is not ready after {}s. " +
                    "You should increase `network_ready_timeout`. Continuing anyway..."
                ).format(self.network_ready_timeout)
            )

        self.logger.info(
            "Network _{}_ ready. Nodes discovered: {}".format(
                'possibly' if timeout else 'really', self.network.nodes_count,
            )
        )

        started = True

        return (True, 'OK')


    def stop(self):
        """Stop the software representation

        :returns: tuple(bool, string): (status, reason) where:

                status: True on success, False otherwise
                reason: a textual explanation

        Doctests
        ++++++++

        # >>> print("*** Action needed for node to be _removed_ ***") # doctest:+ELLIPSIS
        # *** ...
        # >>> t.remove_node() # doctest:+ELLIPSIS
        # {...}
        """
        global started

        self.logger.info("Z-Wave Network stopping...")
        try:
            self.network.stop()
        except Exception as e:
            return (False, str(e))

        started = False

        return (True, 'OK')


    def hard_reset(self, force=False):
        """Resets the controller and erases its network configuration settings.  The
        controller becomes a primary controller ready to add nodes to a new
        network. Warning! This basically destroys the network -- use with care!

        :returns: tuple(bool, string): (status, reason) where:

        :raises: RuntimeError exception if network is not empty (nodes are
                included) while `force=False`
        """
        if self.network.nodes_count == 1:
            self.network.controller.hard_reset()
            return (True, 'OK')
        elif force:
            self.logger.warning("Forcing hard reset on a network with included nodes.")
            self.network.controller.hard_reset()
            return (True, 'OK')
        else:
            raise RuntimeError("Cannot hard reset while network has included nodes.")


    def soft_reset(self):
        """Soft reset the controller. The software representation is untouched.

        :returns: tuple(bool, string): (status, reason) where:
        """
        try:
            self.network.controller.soft_reset()
        except Exception as e:
            return (False, str(e))

        return (True, 'OK')


    def network_info(self):
        
        """Get network's structure information summary.

        :returns: dict: with various info about the network and currently
                associated nodes
        """
        #### COMPLETE THIS METHOD ####

        self.logger.debug('(network_info) testing logger')
        print('(network_info) testing logger')
        result = {
            'Network Home ID':  self.network.home_id_str,
            'Server status' : self.network.state
        }
        for node in self._my_nodes().values():
            result[node.node_id] = {
                "Is Ready": node.is_ready,
                "Neighbours": list(node.neighbors),
                "Node ID": node.node_id,
                "Node location": node.location,
                "Node Name": node.name,
                "Node type": node.type,
                "Product Name": node.product_name,
            }
        return result
        


    def get_nodes_configuration(self):
        """Get an overview of the network and its nodes' configuration parameters (ID,
        Wake-up Interval, Group 1 Reports, Group 1 Interval, ...).

        :returns: dict: the nodes's configuration parameters
        """
        result = {
            'Network Home ID':  self.network.home_id_str
        }

        self.logger.debug("looking for nodes...")
        for node in self._my_nodes().values():
            if node.is_ready and not self._is_controller(node):
                # Update of the software representation: retreive the last
                # status of the Z-Wave network
                node.request_all_config_params()

                # Get Config + System values
                values = node.get_values(
                    class_id="All",
                    genre="Config",
                    readonly="All",
                    writeonly=False,
                    label="All"
                )

                # de-obectify for json serialization. `values` is something like:
                # int(ID): {
                #     'label': str,
                #     'value_id': int(ID), # same as master key
                #     'node_id': int,
                #     'units': str,
                #     'genre': str,
                #     'data': str,
                #     'data_items': set(...), # this is not jsonify-able!
                #     'command_class': int,
                #     'is_read_only': bool,
                #     'is_write_only': bool,
                #     'type': str,
                #     'index': int
                # }
                # which must be inspected for deep serialization
                nodeValues = {
                    clsid: json_prepare(data) for clsid, data in values.items()
                }
                nodeValues['Node type'] = str(node.type)
                result[node.node_id] = nodeValues

        return result


    def get_nodes_list(self):
        """Get a list of all the nodes in the network, where indexes are
        node IDs and values are product names.

        :returns: object: an `OrderedDict` indexed by node IDs with product
                names (or a "[not ready]" note) as values:

            {
              "1": "Z-Stick Gen5",
              "2": "MultiSensor 6",
              "3": "ZE27",
              "4": "[not ready]"
            }
        """
        
        #### COMPLETE THIS METHOD ####
        #return self._my_nodes()
        #Test
        #self.network.controller.add_node()
        #return self.network.nodes[self.network.nodes_count-1]

        result = {
            #'Network Home ID':  self.network.home_id_str
        }

        self.logger.debug("looking for nodes...")
        for node in self._my_nodes().values():
            if node.is_ready:
                result[node.node_id]=str(node.type)
            else:
                result[node.node_id]="[not ready]"
        
        return result


    def get_sensors_list(self):
        """Get a list of sensor nodes in the network, where indexes are
        node IDs and values are product names.

        :returns: object: an `OrderedDict` indexed by node IDs with product
                names (or a "[not ready]" note) as values:

            {
                "2": "MultiSensor 6",
                "3": "MultiSensor 6"
            }
        """
        #### COMPLETE THIS METHOD ####
        result = {
            #'Network Home ID':  self.network.home_id_str
        }
        for node in self._my_nodes().values():
            if self._is_sensor(node):
                if node.is_ready:
                    result[node.node_id]=str(node.product_name)
                else:
                    result[node.node_id]="[not ready]"
        
        return result

    def get_dimmers_list(self):
        """Get a list of dimmer nodes in the network, where indexes are
        node IDs and values are product names.

        :returns: object: an `OrderedDict` indexed by node IDs with product
                names (or a "[not ready]" note) as values:

            {
                "2": "???",
                "3": ""
            }
        """
        #### COMPLETE THIS METHOD ####
        result = {
            #'Network Home ID':  self.network.home_id_str
        }

        self.logger.debug("looking for nodes...")
        for node in self._my_nodes().values():
            if self._is_dimmer(node):
                if node.is_ready:
                    result[node.node_id]=str(node.product_name)
                else:
                    result[node.node_id]="[not ready]"
        
        return result
       


    ############################################################################
    # @nodes
    ############################################################################

    def _my_nodes(self):
        """Returns an ordered list of the all network's nodes sorted by node's
        ID.

        :returns: object: an :class:`OrderedDict`

        """
        return OrderedDict(sorted(self.network.nodes.items()))


    def _is_controller(self, node):
        """Check if node is a controller.

        :param object node: a :class:`openzwave.node`

        :returns: bool
        """
        return node.node_id == self.CONTROLLER_NODE_ID


    def _is_dimmer(self, node):
        """Check if node is a dimmer by matching its type against
        :attr:`self.re_dimmer`.

        :param object node: a :class:`openzwave.node`

        :returns: bool

        """
        return re.search(self.re_dimmer, node.type, re.I)


    def _is_sensor(self, node):
        """Check if node is a sensor by matching its type against
        :attr:`self.re_sensor`.

        :param object node: a :class:`openzwave.node`

        :returns: bool

        """
        return re.search(self.re_sensor, node.type, re.I)


    @staticmethod
    def _lookup_value(values, label):
        """Look up a (node's) value by label in a list of values.

        :param string label: the wanted value's label
        :param values set: a value set as returned by :func:`node.get_values()`

        :returns: depends on the value's type or None if the wanted value
                is not found
        """
        return next(
            (value.date for value in values if value.label == label),
            None # default
        )

    def _has_timestamp(self, node):
        """Check if a node has a timestamp, meaning that it should be ready and has
        received a first value update.

        :param object node: a :class:`openzwave.node`

        :returns: bool: True if an entry exists in `self.timestamps`
        """
        self.logger.debug("timestamps: {}".format(self.timestamps))
        return _tstamp_label(node) in self.timestamps


    def _get_node_timestamp(self, node):
        """Get the last update time of a node.

        :param object node: a :class:`openzwave.node`

        :returns: int: time as seconds-since-th-epoch ([FIX-ME] to be verfied)
                or None if no timestamp exists for `node`
        """
        try:
            return  self.timestamps[_tstamp_label(node)]
        except KeyError:
            return None

    def _set_node_timestamp(self, node, value):
        """Set the last update time of a node.

        :param object node: a :class:`openzwave.node`
        :param int value: time as seconds-since-the-epoch

        :returns: None
        """
        self.timestamps[_tstamp_label(node)] = value

    def _del_node_timestamp(self, node):
        """Remove the last update time of a node.

        :param object node: a :class:`openzwave.node`

        :returns: int: time as seconds-since-th-epoch ([FIX-ME] to be verfied)
                or None if no timestamp exists for `node`
        """
        return self.timestamps.pop(_tstamp_label(node), None)


    def add_node(self):
        """Adds a node to the network by switching the controller into
        inclusion mode for 20 seconds. The node to add can not be a
        controller. Physical action is required on the node to be added.

        :returns: object: the added node's :class:`openzwave.node` object

        :raises: RuntimeError exception if
                * timeout occurs, or
                * network is not started
        """

        #### COMPLETE THIS METHOD ####
        
        #Block for 20 s and check for event ?
        """
        for i in range(20):
            if self.network.SIGNAL_NODE_ADDED:
                break
            sleep(1)
        """

        #Attention à resetter le flag node_added avant la add_node() car il y a un bug quelque part dans le pyozw comme quoi une add qui échoue pourrait laisser le flag setté.
        if not self._network_started:
            raise RuntimeError("Network is down")

        temp=self.node_added
        if(self.network.controller.add_node()):
            start = time.time()
         #: The controller is waiting for a user action. A notice should be displayed  
            self.logger.debug('(add) add signal sent, entering while')
            while self.node_added==temp:
                if (time.time()-start) > self.controller_operation_timeout:
                    print('Timed out')
                    self.network.controller.cancel_command()
                    raise RuntimeError("Timeout")            
            return json_prepare(self.node_added)

    def remove_node(self):
        """Removes a node from the network by switching the controller into
        exclusion mode for 20 seconds. The node to remove can not be a
        controller. Physical action is required on the node to be removed.

        :returns: object: the removed node's :class:`openzwave.node` object

        :raises: RuntimeError exception if
                * timeout occurs, or
                * network is not started
        """
        #### COMPLETE THIS METHOD ####
        if not self._network_started:
            raise RuntimeError("Network is down")
            
        temp=self.node_removed
        if(self.network.controller.remove_node()):
            start = time.time()
         #: The controller is waiting for a user action. A notice should be displayed  
            self.logger.debug('(remove) add signal sent, entering while')
            while self.node_removed==temp:
                if (time.time()-start) > self.controller_operation_timeout:
                    print('Timed out')
                    self.network.controller.cancel_command()
                    raise RuntimeError("Timeout")            
            return json_prepare(self.node_removed)

    def set_node_location(self, n, value):
        """Set a node's location.

        :param int n: the node's ID
        :param str value: the new location value

        :returns: str: The previous location value

        :raises: RuntimeError: if the node is not found
        """
        #### COMPLETE THIS METHOD ####
        node = self._lookup_node(n)

        if not node:
            raise RuntimeError("No node with this ID")
        else:
            temp = node.location
            node.location = value
            return temp

    def set_node_name(self, n, value):
        """Set a node's name.

        :param int n: the node's ID
        :param str value: the new name value

        :returns: str: The previous name value

        :raises: RuntimeError: if the node is not found
        """
        #### COMPLETE THIS METHOD ####
        node = self._lookup_node(n)

        if not node:
            raise RuntimeError("No node with this ID")
        else:
            temp = node.name
            node.name = value
            return temp

    def get_node_location(self, n):
        """Get a node's location.

        :param int n: the node's ID

        :returns: str: the location value on succes

        :raises: RuntimeError: if the node is not found
        """
        node = self._lookup_node(n)
        if not node:
            raise RuntimeError("No such node")

        return node.location


    def get_node_name(self, n):
        """Get a node's name.

        :param int n: the node's ID

        :returns: int: the name value on succes

        :raises: RuntimeError: if the node is not found
        """
        #### COMPLETE THIS METHOD ####
        node = self._lookup_node(n)
        if not node:
            raise RuntimeError("No such node")

        return node.name

    def get_neighbours_list(self, n):
        """Get a node's llist of neighbors.

        :param int n: the node's ID

        :returns: tuple: the neighbors' numerical ID list (might be empty)

        :raises: RuntimeError: if the node is not found
        """
        #### COMPLETE THIS METHOD ####
        node = self._lookup_node(n)
        if not node:
            raise RuntimeError("No such node")

        return node.neighbors

    def set_node_parameter(self, n, pindex, value, size):
        """Sets a node's configuration parameter. There's no guarantee that the
        parameter has been set -- you may check with
        `get_node_parameter()`.

        :param int n: the node's ID
        :param int pindex: the parameter's index
        :param int value: the parameter's value
        :param int value: the parameter's size

        :returns: bool: True on success. False if the command wan't sent for
                some reason (see OZW log)

        :raises: RuntimeError: if the node is not found
        """
        #### COMPLETE THIS METHOD ####
        node = self._lookup_node(n)
        if not node:
            raise RuntimeError("No such node")

        return node.set_config_param(pindex,value,size)

    def get_node_parameter(self, n, pindex):
        """Get a node's configuration parameter.

        :param int n: the node's ID
        :param int pindex: the parameter's index
    
        :returns: int: the parameter value on succes, or None if the
                parameters is not found

        :raises: RuntimeError: if the node is not {found | ready}
        """
        #### COMPLETE THIS METHOD ####

        node = self._lookup_node(n)
        if not node:
            raise RuntimeError("No such node")

        node.node.request_all_config_params()
        #node.requestConfigParam() #Would probably be better 
        return list(node.get_values())[pindex]

        if list(node.values.values())[pindex] == None:
            raise RuntimeError("No such param")
        else:
            return json_prepare(list(node.values.values())[pindex])

################################################################################
################################################################################
class Backend_with_sensors(Backend):
    """Backend with sensors class
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


    def get_sensor_temperature(self, n):
        """Get a sensor's temperature.

        :param int n: the node's ID

        :returns: dict: on success, see doctests below; else raises an exception

        :raises: RuntimeError: if the node is not {found | ready | sensor}

        Doctests
        ++++++++

        >>> t.get_temperature(2)
        {
            "controller": ...,
            "sensor": ...,
            "location": ...,
            "type": 'Temperature',
            "updateTime": ...,
            "value": ...
        }
        """
        node = self._lookup_sensor_node(n)

        # <http://www.openzwave.com/dev/classOpenZWave_1_1SensorMultilevel.html>
        values = node.get_values(
            class_id=0x31,      # COMMAND_CLASS_SENSOR_MULTILEVEL
            genre="User", readonly=True, writeonly=False,
            label=self._labels_xref['temperature']
        )

        if not values:
            raise RuntimeError("Temperature: label not found. Is this a sensor?")

        # who cares if more => bug??? Check the get_values() above
        if len(values) > 1:
            self.logger.warning(
                "Node {}: get_values(Temperature) returned more than one value!?".format(
                    node.node_id
                )
            )

        # [BUG] WTF, value is °F?? <https://aeotec.freshdesk.com/support/solutions/articles/6000036562-multisensor-6-firmware-update-6-17-2016->
        value = [
            v.data if v.units == 'C' else f_to_c(v.data)
            for k,v in values.items()
        ][0]

        return {
            "controller": self.controller_name,
            "sensor": node.node_id,
            "location": node.location,
            "type": 'temperature',
            "updateTime": self._get_node_timestamp(node),
            "value": value
        }


    def get_sensor_humidity(self, n):
        """Get a sensor's humidity.

        :param int n: the node's ID

        :returns: dict: on success, see doctests below; else raises an exception

        :raises: RuntimeError: if the node is not {found | ready | sensor}

        Doctests
        ++++++++

        >>> t.get_humidity(2)
        {
            "controller": ...,
            "sensor": ...,
            "location": ...,
            "type": 'humidity',
            "updateTime": ...,
            "value": ...
        }
        """
        #### COMPLETE THIS METHOD ####
        node = self._lookup_sensor_node(n)

        # <http://www.openzwave.com/dev/classOpenZWave_1_1SensorMultilevel.html>
        values = node.get_values(
            class_id=0x31,      # COMMAND_CLASS_SENSOR_MULTILEVEL
            genre="User", readonly=True, writeonly=False,
            label=self._labels_xref['humidity']
        )

        if not values:
            raise RuntimeError("Humidity: label not found. Is this a sensor?")

        # who cares if more => bug??? Check the get_values() above
        if len(values) > 1:
            self.logger.warning(
                "Node {}: get_values(Humidity) returned more than one value!?".format(
                    node.node_id
                )
            )

        value = [
            v.data #if v.units == 'C' else f_to_c(v.data)
            for k,v in values.items()
        ][0]

        return {
            "controller": self.controller_name,
            "sensor": node.node_id,
            "location": node.location,
            "type": 'humidity',
            "updateTime": self._get_node_timestamp(node),
            "value": value
        }

    def get_sensor_luminance(self, n):
        """Get a sensor's luminance.

        :param int n: the node's ID

        :returns: dict: on success, see doctests below; else raises an exception

        :raises: RuntimeError: if the node is not {found | ready | sensor}

        Doctests
        ++++++++

        >>> t.get_luminance(2)
        {
            "controller": ...,
            "sensor": ...,
            "location": ...,
            "type": 'luminance',
            "updateTime": ...,
            "value": ...
        }
        """
        #### COMPLETE THIS METHOD ####

        node = self._lookup_sensor_node(n)

        # <http://www.openzwave.com/dev/classOpenZWave_1_1SensorMultilevel.html>
        values = node.get_values(
            class_id=0x31,      # COMMAND_CLASS_SENSOR_MULTILEVEL
            genre="User", readonly=True, writeonly=False,
            label=self._labels_xref['luminance']
        )

        if not values:
            raise RuntimeError("luminance: label not found. Is this a sensor?")

        # who cares if more => bug??? Check the get_values() above
        if len(values) > 1:
            self.logger.warning(
                "Node {}: get_values(Luminance) returned more than one value!?".format(
                    node.node_id
                )
            )

        value = [
            v.data if v.units == 'C' else f_to_c(v.data)
            for k,v in values.items()
        ][0]

        return {
            "controller": self.controller_name,
            "sensor": node.node_id,
            "location": node.location,
            "type": 'luminance',
            "updateTime": self._get_node_timestamp(node),
            "value": value
        }


    def get_sensor_ultraviolet(self, n):
        """Get a sensor's ultraviolet reading.

        :param int n: the node's ID

        :returns: dict: on success, see doctests below; else raises an exception

        :raises: RuntimeError: if the node is not {found | ready | sensor}

        Doctests
        ++++++++

        >>> t.get_ultraviolet(2)
        {
            "controller": ...,
            "sensor": ...,
            "location": ...,
            "type": 'ultraviolet',
            "updateTime": ...,
            "value": ...
        }
        """
        #### COMPLETE THIS METHOD ####

        node = self._lookup_sensor_node(n)

        # <http://www.openzwave.com/dev/classOpenZWave_1_1SensorMultilevel.html>
        values = node.get_values(
            class_id=0x31,      # COMMAND_CLASS_SENSOR_MULTILEVEL
            genre="User", readonly=True, writeonly=False,
            label=self._labels_xref['ultraviolet']
        )

        if not values:
            raise RuntimeError("ultraviolet: label not found. Is this a sensor?")

        # who cares if more => bug??? Check the get_values() above
        if len(values) > 1:
            self.logger.warning(
                "Node {}: get_values(ultraviolet) returned more than one value!?".format(
                    node.node_id
                )
            )

        value = [
            v.data #if v.units == 'C' else f_to_c(v.data)
            for k,v in values.items()
        ][0]

        return {
            "controller": self.controller_name,
            "sensor": node.node_id,
            "location": node.location,
            "type": 'ultraviolet',
            "updateTime": self._get_node_timestamp(node),
            "value": value
        }

    def get_sensor_motion(self, n):
        """Get a sensor's motion.

        :param int n: the node's ID

        :returns: dict: on success, see doctests below; else raises an exception

        :raises: RuntimeError: if the node is not {found | ready | sensor}

        Doctests
        ++++++++

        >>> t.get_motion(2)
        {
            "controller": ...,
            "sensor": ...,
            "location": ...,
            "type": 'motion',
            "updateTime": ...,
            "value": ...
        }
        """
        #### COMPLETE THIS METHOD ####
        node = self._lookup_sensor_node(n)

        # <http://www.openzwave.com/dev/classOpenZWave_1_1SensorMultilevel.html>
        values = node.get_values(
            class_id=0x31,      # COMMAND_CLASS_SENSOR_MULTILEVEL
            genre="User", readonly=True, writeonly=False,
            label=self._labels_xref['motion']
        )

        if not values:
            raise RuntimeError("ultraviolet: label not found. Is this a sensor?")

        # who cares if more => bug??? Check the get_values() above
        if len(values) > 1:
            self.logger.warning(
                "Node {}: get_values(motion) returned more than one value!?".format(
                    node.node_id
                )
            )

        value = [
            v.data #if v.units == 'C' else f_to_c(v.data)
            for k,v in values.items()
        ][0]

        return {
            "controller": self.controller_name,
            "sensor": node.node_id,
            "location": node.location,
            "type": 'motion',
            "updateTime": self._get_node_timestamp(node),
            "value": value
        }


    def get_sensor_battery(self, n):
        """Get a sensor's battery level.

        :param int n: the node's ID

        :returns: dict: on success, see doctests below; else raises an exception

        :raises: RuntimeError: if the node is not {found | ready | sensor}

        Doctests
        ++++++++

        >>> t.get_motion(2)
        {
            "controller": ...,
            "sensor": ...,
            "location": ...,
            "type": 'motion',
            "updateTime": ...,
            "value": ...
        }
        """
        #### COMPLETE THIS METHOD ####
        node = self._lookup_sensor_node(n)

        # <http://www.openzwave.com/dev/classOpenZWave_1_1SensorMultilevel.html>
        values = node.get_values(
            class_id=0x31,      # COMMAND_CLASS_SENSOR_MULTILEVEL
            genre="User",# readonly=True, writeonly=False,
            label=self._labels_xref['battery']
        )

        if not values:
            raise RuntimeError("battery: label not found. Is this a sensor?")

        # who cares if more => bug??? Check the get_values() above
        if len(values) > 1:
            self.logger.warning(
                "Node {}: get_values(battery) returned more than one value!?".format(
                    node.node_id
                )
            )

        value = [
            v.data #if v.units == 'C' else f_to_c(v.data)
            for k,v in values.items()
        ][0]

        return {
            "controller": self.controller_name,
            "sensor": node.node_id,
            "location": node.location,
            "type": 'battery',
            "updateTime": self._get_node_timestamp(node),
            "value": value
        }

    def get_sensor_readings(self, n):
        """Get all measurements for a sensor.

        :param int n: the node's ID

        :returns: dict: the measurements value on succes, or None if the
                requested node is not found

        :raises: RuntimeError: if the node is not {found | ready | sensor}

        Doctests
        ++++++++

        >>> t.get_all_readings(2)
        {
            "controller": ...,
            "sensor": ...,
            "location": ...,
            "type": 'motion',
            "updateTime": ...,
            "value": ...
        }
        """
        #### COMPLETE THIS METHOD ####
        node = self._lookup_sensor_node(n)

        d = {}
        d.update({"value temperature":self.get_sensor_temperature(n).get("value")})
        d.update({"value humidity":self.get_sensor_humidity(n).get("value")})
        d.update({"value luminance":self.get_sensor_luminance(n).get("value")})
        d.update({"value ultraviolet":self.get_sensor_ultraviolet(n).get("value")})
        d.update({"value battery":self.get_sensor_battery(n).get("value")})       
        return d


    def set_sensors_parameter(self, index, value, size):
        """Set a configuration parameter for all sensor nodes in the network.

        :param int index: the parameter's index
        :param int value: the parameter's value
        :param int value: the parameter's size

        :returns: dict: for each sensor node's ID (dict's key), a tuple(bool,
            string):

                {
                    "<node-ID>": (status, reason),
                    ...
                }

            where:

                status: True on success, False if the network was already start
                reason: a textual explanation

        :raises: RuntimeError: if network is not started
        """
        

        #### COMPLETE THIS METHOD ####


        if not self.network._is_network_started():
            raise RuntimeError("Network not started")

        result = {
            'Network Home ID':  self.network.home_id_str
        }

        nodes = self.get_sensors_list()

        for node in nodes:

            #node = self._lookup_dimmer_node(n)
            node.request_all_config_params()
            # <http://www.openzwave.com/dev/classOpenZWave_1_1SensorMultilevel.html>
            values = node.get_values(
                #class_id=0x31,      # COMMAND_CLASS_SENSOR_MULTILEVEL
                genre="User", #readonly=True, writeonly=False,
                #label=self._labels_xref['level']
                index=index

            )

            if not values:
                raise RuntimeError("Temperature: label not found. Is this a sensor?")

            # who cares if more => bug??? Check the get_values() above
            if len(values) > 1:
                self.logger.warning(
                    "Node {}: get_values(Temperature) returned more than one value!?".format(
                        node.node_id
                    )
                )

            # [BUG] WTF, value is °F?? <https://aeotec.freshdesk.com/support/solutions/articles/6000036562-multisensor-6-firmware-update-6-17-2016->
            value = [
                v.data #if v.units == 'C' else f_to_c(v.data)
                for k,v in values.items()
            ][0]

            nodeValues = {
                clsid: json_prepare(data) for clsid, data in values.items()
            }

            nodeValues['Node type'] = str(node.node_id)
            result[node.node_id] = nodeValues
        return result


################################################################################
################################################################################
class Backend_with_dimmers(Backend):
    """Handle dimmers
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


    def get_dimmer_level(self, n):
        """Get a sensor's humidity.

        :param int n: the node's ID

        :returns: dict: on success, see doctests below; else raises an exception

        :raises: RuntimeError: if the node is not {found | ready | dimmer}

        Doctests
        ++++++++

        >>> t.get_dimmer_level(3)
        {
            "controller": ...,
            "dimmer": ...,
            "location": ...,
            "type": 'level',
            "value": ...
        }
        """
        #### COMPLETE THIS METHOD ####

        node = self._lookup_node(n)

        if not node:
            raise RuntimeError("No such node")

        if not (node.is_ready or self._has_timestamp(node)):
            raise RuntimeError("Not ready")

        if not self._is_dimmer(node):
            raise RuntimeError("Not a dimmer")

        #node = self._lookup_dimmer_node(n)

        # <http://www.openzwave.com/dev/classOpenZWave_1_1SensorMultilevel.html>
        values = node.get_values(
            #class_id=0x31,      # COMMAND_CLASS_SENSOR_MULTILEVEL
            genre="User", #readonly=True, writeonly=False,
            label=self._labels_xref['level']
        )

        if not values:
            raise RuntimeError("Temperature: label not found. Is this a sensor?")

        if len(values) > 1:
            self.logger.warning(
                "Node {}: get_values(Temperature) returned more than one value!?".format(
                    node.node_id
                )
            )

        value = [
            v.data #if v.units == 'C' else f_to_c(v.data)
            for k,v in values.items()
        ][0]

        return {
            "controller": self.controller_name,
            "dimmer": node.node_id,
            "location": node.location,
            "type": 'level',
            "value": value
        }

    def set_dimmer_level(self, n, value):
        """Set a dimmer's level.

        :param int n: the node's ID
        :param str value: the new level value

        :returns: str: The previous level value

        :raises: RuntimeError: if the node is not {found | ready | dimmer}
        """
        #### COMPLETE THIS METHOD ####
        node = self._lookup_node(n)

        if not node:
            raise RuntimeError("No such node")

        if not (node.is_ready):
            raise RuntimeError("Not ready")

        if not self._is_dimmer(node):
            raise RuntimeError("Not a dimmer")

        # <http://www.openzwave.com/dev/classOpenZWave_1_1SensorMultilevel.html>
        values = node.get_values(
            #class_id=0x31,      # COMMAND_CLASS_SENSOR_MULTILEVEL
            genre="User", #readonly=True, writeonly=False,
            label=self._labels_xref['level']
        )

        if not values:
            raise RuntimeError("Temperature: label not found. Is this a sensor?")

        # who cares if more => bug??? Check the get_values() above
        if len(values) > 1:
            self.logger.warning(
                "Node {}: get_values(Temperature) returned more than one value!?".format(
                    node.node_id
                )
            )
        temp= [#previous value
            v.data #if v.units == 'C' else f_to_c(v.data)
            for k,v in values.items()
        ][0]

        value_id= [#previous value
            v.value_id #if v.units == 'C' else f_to_c(v.data)
            for k,v in values.items()
        ][0]

        node.set_dimmer(value_id,value)

        return temp



################################################################################
################################################################################
class Backend_with_dimmers_and_sensors(Backend_with_dimmers, Backend_with_sensors):
    """Handle bot dimmers and sensors. This is the main class to be used upstrem,
    e.g., by the flask application
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


################################################################################
################################################################################
if __name__ == '__main__':
    import doctest

    print("*** Doctests: logging to '/tmp/OZW' ***")
    doctest.testmod(
        extraglobs={
            't': Backend_with_dimmers_and_sensors(
                ozw_user_path="/tmp/OZW",
                log_level=logging.DEBUG
            ),
            # 'l': logger,
            # 'data': _test_data
        },
        # verbose=True
    )


# To forcefully start the Python debugger (~hardcoded breakpoint), place the
# following line (uncommented) before the problematic part:
#
#   import ipdb; ipdb.set_trace();
#

