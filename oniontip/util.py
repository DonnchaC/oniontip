import json
import shlex
import math
import re
import bitcoinaddress

import json
import operator
import sys
import os
import urllib
import itertools
from stem.descriptor.remote import DescriptorDownloader
from oniontip import db


FAST_EXIT_BANDWIDTH_RATE = 95 * 125 * 1024     # 95 Mbit/s
FAST_EXIT_ADVERTISED_BANDWIDTH = 5000 * 1024   # 5000 kB/s
FAST_EXIT_PORTS = [80, 443, 554, 1755]
FAST_EXIT_MAX_PER_NETWORK = 2

ALMOST_FAST_EXIT_BANDWIDTH_RATE = 80 * 125 * 1024    # 80 Mbit/s
ALMOST_FAST_EXIT_ADVERTISED_BANDWIDTH = 2000 * 1024  # 2000 kB/s
ALMOST_FAST_EXIT_PORTS = [80, 443]

def JSON(val):
  try:
    return json.loads(val)
  except (ValueError,TypeError):
    return []

def List(val):
  if val:
    lex = shlex.shlex(val.encode('ascii','ignore'))
    lex.whitespace += "[],"
    return list(lex)
  else:
    return []

def NullFn(val):
  return val

def Int(val):
  try:
    return int(val)
  except:
    return None

def Boolean(val):
  if val == True:
    return True

  if val in ("false", "False", "FALSE", "F"):
    return False
  if val in ("true", "True", "TRUE", "T"):
    return True

  return False

class Opt(object):
    option_details = {
      'by_as':(Boolean, False),
      'by_country':(Boolean, False),
      'by_network_family':(Boolean, False),
      'inactive':( Boolean, False ),
      'exits_only':( Boolean, False ),
      'guards_only': ( Boolean, False),
      'links':( Boolean, True ),
      'sort':( NullFn, "cw" ),
      'sort_reverse':( Boolean, True ),
      'top':( Int , 5),
      'family':( NullFn, "" ),
      'ases':( List, [] ),
      'country':( JSON, [] ),
      'exit_filter':( NullFn, "all_relays" )
    }


    @staticmethod
    def convert(key,val):
      return Opt.option_details[key][0](val)

    @staticmethod
    def default(key):
      return Opt.option_details[key][1]

    def __str__(self):
      return repr(self)

    def __repr__(self):
      return str(self.__dict__)

    def __init__(self,request):
      for key in Opt.option_details:
        if key in request:
          setattr(self,key,Opt.convert(key,request[key]))
        else:
          setattr(self,key,Opt.default(key))

class Result():
    WEIGHT_FIELDS = {
    'consensus_weight_fraction': 'cw', 
    'advertised_bandwidth_fraction': 'adv_bw',
    'guard_probability': 'p_guard',
    'middle_probability': 'p_middle',
    'exit_probability': 'p_exit',
    }

    def __init__(self, zero_probs = False):
        self.index = None
        self.donation_share = 0.0
        self.cw = 0.0 if zero_probs else None
        self.adv_bw = 0.0 if zero_probs else None
        self.p_guard = 0.0 if zero_probs else None
        self.p_exit = 0.0 if zero_probs else None
        self.p_middle = 0.0 if zero_probs else None
        self.nick = ""
        self.fp = ""
        self.link = True
        self.exit = ""
        self.guard = ""
        self.cc = ""
        self.primary_ip = ""
        self.as_no = ""
        self.as_name = ""
        self.as_info = ""
        self.bitcoin_address = ""

    def __getitem__(self,prop):
      getattr(self,prop)

    def __setitem__(self,prop,val):
      setattr(self,prop,val)

    def jsonify(self):
      return self.__dict__

    def printable_fields(self,links=False):
      """
      Return this Result object as a list with the fields in the order
      expected for printing.
      """
      format_str = "%.4f%%|%.4f%%|%.4f%%|%.4f%%|%.4f%%|%s|%s|%s|%s|%s|%s|%s"
      formatted = format_str % ( self.cw, self.adv_bw, self.p_guard, self.p_middle, self.p_exit,
                    self.nick, 
                    "https://atlas.torproject.org/#details/" + self.fp if links else self.fp,
                    self.exit, self.guard, self.cc, self.primary_ip, self.as_info,  )
      return formatted.split("|")

class ResultEncoder(json.JSONEncoder):
  def default(self,obj):
    if isinstance(obj,Result):
      return obj.__dict__
    return json.JSONEncoder.default(self,obj)

def extract_bitcoin_address(field):
    bitcoin_match = re.search(r"[13][a-km-zA-HJ-NP-Z0-9]{26,33}", field)
    if bitcoin_match:
        bitcoin_address = bitcoin_match.group(0)
        if bitcoinaddress.validate(bitcoin_address):
            return bitcoin_address


def calculate_fee(num_inputs, num_outputs, kb_tx_fee):
    '''
    Constants based on https://bitcoin.stackexchange.com/a/17331
    '''
    estimate_size = float((148 * num_inputs) + (34 * num_outputs) + 10)
    return int(math.ceil(estimate_size / 1000) * kb_tx_fee)

class BaseFilter(object):
    def accept(self, relay):
        raise NotImplementedError("This isn't implemented by the subclass")

    def load(self, relays):
        return filter(self.accept, relays)

class CountryFilter(BaseFilter):
    def __init__(self, countries=[]):
        self._countries = [x.lower() for x in countries]

    def accept(self, relay):
        return relay.get('country', None) in self._countries

class ExitFilter(BaseFilter):
    def accept(self, relay):
        return relay.get('exit_probability', -1) > 0.0

class GuardFilter(BaseFilter):
    def accept(self, relay):
        return relay.get('guard_probability', -1) > 0.0

class InverseFilter(BaseFilter):
    def __init__(self, orig_filter):
        self.orig_filter = orig_filter

    def load(self, all_relays):
        matching_relays = self.orig_filter.load(all_relays)
        inverse_relays = []
        for relay in all_relays:
            if relay not in matching_relays:
                inverse_relays.append(relay)
        return inverse_relays

class BitcoinFilter(BaseFilter):
    ''' Select relays from which a bitcoin address has been extracted''' 
    class Relay(object):
        def __init__(self, relay):
            self.relay = relay

    def load(self, all_relays):
        matching_relays = []
        for relay in all_relays:
            if 'bitcoin_address' in relay:
                matching_relays.append(relay)
        return matching_relays

class RelayStats(object):
    def __init__(self, options, custom_datafile="details.json"):
        self._data = None
        self._datafile_name = custom_datafile
        self._filters = self._create_filters(options)
        self._get_group = self._get_group_function(options)
        self._relays = None
        #slef._relays_published = None

    @property
    def data(self):
      if not self._data:
        self._data = json.load(file(os.path.join(os.path.dirname(os.path.abspath(__file__)), self._datafile_name)))
      return self._data

    @property
    def relays(self):
        if self._relays:
            return self._relays
        self._relays = {}
        relays = self.data['relays']
        for f in self._filters:
            relays = f.load(relays)
        for relay in relays:
            self.add_relay(relay)
        return self._relays

    def _create_filters(self, options):
        filters = []
        # Filter for relays with Bitcoin address
        filters.append(BitcoinFilter())
        if options.country:
            filters.append(CountryFilter(options.country))
        if options.exits_only:
            filters.append(ExitFilter())
        if options.guards_only:
            filters.append(GuardFilter())
        return filters

    def _get_group_function(self, options):
        funcs = []
        funcs.append(lambda relay: relay.get('fingerprint'))
        return lambda relay: tuple([func(relay) for func in funcs])

    def add_relay(self, relay):
        key = self._get_group(relay)
        if key not in self._relays:
            self._relays[key] = []
        self._relays[key].append(relay)

    WEIGHTS = ['consensus_weight_fraction', 'advertised_bandwidth_fraction', 'guard_probability', 'middle_probability', 'exit_probability']

    def sort_and_reduce(self, relay_set, options):
      """
      Take a set of relays (has already been grouped and
      filtered), sort it and return the ones requested
      in the 'top' option.  Add index numbers to them as well.

      Returns a hash with three values: 
        *results*: A list of Result objects representing the selected
                   relays
        *excluded*: A Result object representing the stats for the 
                    filtered out relays. May be None
        *total*: A Result object representing the stats for all of the
                 relays in this filterset.
      """
      output_relays = list()
      excluded_relays = None
      output_relays_cw = 0
      total_relays = None

      # We need a simple sorting key function
      def sort_fn(r):
        return getattr(r,options.sort)
      
      relay_set.sort(key=sort_fn,reverse=options.sort_reverse)

      if options.top < 0:
        options.top = len(relay_set)

      # Set up to handle the special lines at the bottom
      excluded_relays = Result(zero_probs=True)
      total_relays = Result(zero_probs=True)
      if options.by_country or options.by_as or options.by_network_family:
          filtered = "relay groups"
      else:
          filtered = "relays"

      # Add selected relays to the result set
      for i,relay in enumerate(relay_set):
        # We have no links if we're grouping
        if options.by_country or options.by_as or options.by_network_family:
          relay.link = False

        if i < options.top:
          relay.index = i + 1
          output_relays.append(relay)
          output_relays_cw += relay.cw

        if i >= options.top:
          excluded_relays.p_guard += relay.p_guard
          excluded_relays.p_exit += relay.p_exit
          excluded_relays.p_middle += relay.p_middle
          excluded_relays.adv_bw += relay.adv_bw
          excluded_relays.cw += relay.cw

        total_relays.p_guard += relay.p_guard
        total_relays.p_exit += relay.p_exit
        total_relays.p_middle += relay.p_middle
        total_relays.adv_bw += relay.adv_bw
        total_relays.cw += relay.cw

        excluded_relays.nick = "(%d other %s)" % (
                                  len(relay_set) - options.top,
                                  filtered)
        total_relays.nick = "(total in selection)"

      # Only include the excluded line if
      if len(relay_set) <= options.top:
        excluded_relays = None

      # Only include the last line if
      if total_relays.cw > 99.9:
        total_relays = None

      for relay in output_relays:
        relay.donation_share = (relay.cw / output_relays_cw) * 100
        total_relays.donation_share += relay.donation_share

      return {
              'results': output_relays,
              'excluded': excluded_relays,
              'total': total_relays
              }


    def select_relays(self, grouped_relays, options): 
      """
      Return a Pythonic representation of the relays result set. Return it as a set of Result objects.
      """
      results = []
      for group in grouped_relays.itervalues():
        #Initialize some stuff
        group_weights = dict.fromkeys(RelayStats.WEIGHTS, 0)
        relays_in_group, exits_in_group, guards_in_group = 0, 0, 0
        ases_in_group = set()
        countries_in_group = set()
        network_families_in_group = set()
        result = Result()
        for relay in group:
            for weight in RelayStats.WEIGHTS:
                group_weights[weight] += relay.get(weight, 0)

            result.nick = relay['nickname']
            result.fp = relay['fingerprint']
            result.link = options.links

            if 'Exit' in set(relay['flags']) and not 'BadExit' in set(relay['flags']):
                result.exit = True
                exits_in_group += 1
            if 'Guard' in set(relay['flags']):
                result.guard = True
                guards_in_group += 1
            result.cc = relay.get('country', '??').lower()
            countries_in_group.add(result.cc)
            result.primary_ip = relay.get('or_addresses', ['??:0'])[0].split(':')[0]
            result.as_no = relay.get('as_number', '??')
            result.as_name = relay.get('as_name', '??')
            result.as_info = "%s %s" %(result.as_no, result.as_name)
            ases_in_group.add(result.as_info)
            result.bitcoin_address = relay.get('bitcoin_address', '')
            relays_in_group += 1

        # If we want to group by things, we need to handle some fields
        # specially
        if options.by_country or options.by_as:
            result.nick = "*"
            result.fp = "(%d relays)" % relays_in_group
            result.exit = "(%d)" % exits_in_group
            result.guard = "(%d)" % guards_in_group
            if not options.by_as and not options.ases:
                result.as_info = "(%d)" % len(ases_in_group)
            if not options.by_country and not options.country:
                result.cc = "(%d)" % len(countries_in_group)
            if not options.by_network_family:
                result.primary_ip = "(%d diff. /16)" % len(network_families_in_group)
            else:
                result.primary_ip = network_families_in_group.pop()

        #Include our weight values
        for weight in group_weights.iterkeys():
          result['cw'] = group_weights['consensus_weight_fraction'] * 100.0
          result['adv_bw'] = group_weights['advertised_bandwidth_fraction'] * 100.0
          result['p_guard'] = group_weights['guard_probability'] * 100.0
          result['p_middle'] = group_weights['middle_probability'] * 100.0
          result['p_exit'] = group_weights['exit_probability'] * 100.0
          
        results.append(result)

      return results

def determine_relays(options):
    stats = RelayStats(options)
    results = stats.select_relays(stats.relays, options)
    relays = stats.sort_and_reduce(results, options)
    relays['relays_published'] = stats.data.get('relays_published')
    return relays

def download_details_file():
    url = urllib.urlopen('https://onionoo.torproject.org/details?type=relay')
    details_file = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'details.json'), 'w')
    details_file.write(url.read())
    url.close()
    details_file.close()

def check_and_update_bitcoin_fields():
    """
    Load full descriptors and parse bitcoin address from X-bitcoin and contact fields then update
    the details.json file with the bitcoin address as a bitcoin_address field. The X-bitcoin field
    takes precedence over the contact field if both both contain bitcoin addresses.
    """
    data = json.load(file(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'details.json')))

    downloader = DescriptorDownloader()
    extracted_addresses = {}
    try:
      # Parse X-bitcoin fields from the network consensus
      for relay_desc in downloader.get_server_descriptors().run():
        x_bitcoin_field = re.search("^X-bitcoin (.*)", str(relay_desc), re.MULTILINE)
        if x_bitcoin_field:
            if extract_bitcoin_address(x_bitcoin_field.group()):
                extracted_addresses[relay_desc.fingerprint] = extract_bitcoin_address(x_bitcoin_field.group())
    except Exception as exc:
        print "Unable to retrieve the network consensus: %s" % exc

    for relay in data['relays']:
        # Check if a bitcoin address was already extracted from X-bitcoin field
        if relay.get('fingerprint') in extracted_addresses:
            relay['bitcoin_address'] = extracted_addresses[relay.get('fingerprint')]

        # Parse bitcoin addresses from the contact field of details.json
        elif relay.get('contact') is not None:
            if extract_bitcoin_address(relay.get('contact')):
                relay['bitcoin_address'] = extract_bitcoin_address(relay.get('contact'))

    # Remove any relays with weight_fraction of -1.0 as they can't be used to determine donation share
    data['relays'][:] = [relay for relay in data['relays'] if not relay['consensus_weight_fraction'] < 0]

    # Write parsed list to file
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'details.json'), 'w') as details_file:
        json.dump(data, details_file)