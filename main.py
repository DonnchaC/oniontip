#!/usr/bin/env python
from oniontip import app, db
from optparse import OptionParser, OptionGroup
import oniontip.util
import oniontip.views
import os
import sys

def create_option_parser():
    parser = OptionParser()
    parser.add_option("-d", "--download", action="store_true",
                      help="download details.json from Onionoo service")
    parser.add_option("-c", "--check", action="store_true",
                      help="check bitcoin addresses for unspent outputs")
    parser.add_option("-a", "--check-all", action="store_true", default=False,
                      help="check all bitcoin addresses for unspent outputs including old addresses")
    return parser

if '__main__' == __name__:
    parser = create_option_parser()
    (options, args) = parser.parse_args()

    if options.download:
        print "Downloading relay details file..."
	relay_data = oniontip.util.download_details_file()
        print "Done."
	
	print "Checking and updating Bitcoin fields"
	oniontip.util.check_and_update_bitcoin_fields(relay_data)
        print "Done."
	print "Downloaded details.json.  Re-run without --download option."
        exit()

    elif options.check or options.check_all:
        # Check recent bitcoin addresses for unspent outputs
        successful_transactions = oniontip.views.find_unsent_payments(check_all=options.check_all)
        if successful_transactions:
            print '{} transactions were successfully sent:'.format(len(successful_transactions))
            for tx in successful_transactions:
                print tx
        else:
            print "No unspent outputs were found for any recent addresses"
        exit()

    # Check details file exists
    if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'oniontip/details.json')):
        sys.exit('Did not find details.json.  Re-run with --download.')

    if not app.config.get('BITCOIN_KEY_SEED'):
        sys.exit('You must set an electrum style private seed in the BITCOIN_KEY_SEED enviromental variable')

    db.create_all()
    app.run()
