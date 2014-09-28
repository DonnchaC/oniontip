from flask import request, jsonify, render_template, Response, send_file
from flask.ext.sqlalchemy import SQLAlchemy

from oniontip import app, db
from models import ForwardAddress, DataStore
import util

import os
import sys
import re
import json
import qrcode
import StringIO
import math
import bitcoin # pybitcointools
import datetime

TX_FEE_PER_KB = 10000   # 
MIN_OUTPUT = 5460       # Bitcoin dust limit

@app.route('/')
def index():
    return render_template('home.html', script_root=request.script_root, total_donated=total_donated())

@app.route('/transactions')
def previous_transactions():
    transactions = []
    payment_addresses = ForwardAddress.query.all()
    for payment in payment_addresses:
        if payment.spent:
            transactions.append({
                'deterministic_index': payment.id,
                'time': payment.created.strftime("%Y-%m-%d %H:%M:%S"),
                'address': payment.address,
                'tx_hash': payment.spending_tx,
                'num_outputs': len(payment.outputs),
                'value': payment.donation_amount,
                'value_formatted': util.format_bitcoin_value(payment.donation_amount)
            })
    return render_template('transactions.html', script_root=request.script_root, total_donated=total_donated(), transactions=transactions)


@app.route('/result.json', methods=['GET'])
def json_result():
    options = util.Opt(dict(request.args.items()))
    relays = util.determine_relays(options)
    return Response(json.dumps(relays, cls=util.ResultEncoder), mimetype='application/json')

@app.route('/payment.json', methods=['GET'])
def payment_info():
    """
    Retrieve and store the selected set of relays's bitcoin addresses with a new bitcoin keypair
    """
    outputs = {}
    options = util.Opt(dict(request.args.items()))
    relays = util.determine_relays(options)

    for relay in relays['results']:
        # If this address already has an output, add the share
        if relay.bitcoin_address in outputs:
            outputs[relay.bitcoin_address] += relay.donation_share
        else:
            outputs[relay.bitcoin_address] = relay.donation_share
            
    if outputs:
        '''
        Retrieve last id and provide it when creating next privkey from seed.
        NOTE: Possible race condition? Two people may get the same address?
        '''
        last_address = ForwardAddress.query.order_by(ForwardAddress.id.desc()).first()
        previous_id = last_address.id if last_address else 0

        donation_request = ForwardAddress(outputs=outputs, previous_n=previous_id)
        db.session.add(donation_request)
        db.session.commit()

        app.logger.info('Forwarding adddress {} paying to {} relays created.'.format(donation_request.address, len(outputs)))
        return Response(json.dumps({
                'status': 'success',
                'data': {
                    'message': 'A new bitcoin address forwarding to the {} selected relays has been created'.format(len(outputs)), 
                    'bitcoin_address': donation_request.address,
                    'num_unique_addresses': len(outputs)
            }}), mimetype='application/json'), 201

    else:
        return Response(json.dumps({'status': 'We could not find any relays which meet your criteria'}), mimetype='application/json'), 400

@app.route('/qr/<address>')
def get_qrcode(address):
    """Generate a QR Code"""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=6,
        border=2,
    )

    qr.add_data('bitcoin:'+str(address))
    qr.make(fit=True)

    img = qr.make_image()

    img_io = StringIO.StringIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)

    return send_file(img_io, mimetype='image/png')

def check_and_send(address):
    '''
    Check generated address and forwarded any unspent outputs

    Check_and_send does the heavy lifting for creating the bitcoin transactions for
    users on the web interface and for requests from the automated cronjob on the CLI
    '''
    try:
        address_history = bitcoin.history(address)
    except Exception, err:
        app.logger.error('Error retrieving address history for {} from blockchain.info: {}'.format(address, str(err)))
        return {'status': 'error',
                'message': '<strong>Blockchain.info Error:</strong> {}'.format(str(err))
                }

    address_unspent = [output for output in address_history if not 'spend' in output]

    if address_history and not address_unspent:
        app.logger.info('Could not find any unspent outputs for address {}, outputs already spent'.format(address))
        return {'status': 'fail',
                'data': { 
                    'message': 'There are no bitcoins remaining at this address. Have they been forwarded already? <a target="_blank" href="https://blockchain.info/address/'+address+'">'+address[0:10]+'..</a>',
                    'code': 404
                }}

    elif not address_unspent:
        app.logger.info('Could not find any unspent outputs for address {}'.format(address))
        return {'status': 'fail',
                'data': {
                    'message': 'No transaction has been received yet.',
                    'code': 404
                }}

    address_info = ForwardAddress.query.filter_by(address=address).first()
    if address_info:
        estimate_fee = util.calculate_fee(num_inputs=len(address_unspent),num_outputs=len(address_info.outputs), kb_tx_fee=TX_FEE_PER_KB)
        unspent_value = sum(output.get('value') for output in address_unspent)
        spendable_value = unspent_value - estimate_fee 
        if spendable_value <= 0:
            app.logger.error('Not enough unspent bitcoin at address {} to pay tx fee of {} satoshi. '.format(address, estimate_fee))
            return {'status': 'fail',
                    'data': {
                        'message': 'There is not enough unspent bitcoin at this address to pay the transaction fee of {} satoshis.'.format(estimate_fee),
                        'code': 500
                    }}
        
        outs = []
        discarded_value = 0
        # Create the outputs, if any are too small, remove them and add them to remaining as can only get bigger
        for address, donation_percent in address_info.outputs.iteritems():
            value = int(math.floor((donation_percent * 0.01) * spendable_value))
            if value >= MIN_OUTPUT:
                outs.append({
                    'address': address,
                    'value': value
                })
            else:
                discarded_value += value
        if discarded_value > 0:
            for out in outs:
                new_ratio = float(out['value']) / (spendable_value - discarded_value)
                out['value'] += int(math.floor(new_ratio * discarded_value))

        if not outs:
            app.logger.error('Could not find addresses suitable to spend to from {}. Outputs may be too small.'.format(address))
            return {'status': 'fail',
                    'data': {
                        'message': 'There are no addresses to where the donation can be successfully forwarded. The value of the donation may be too low, try sending a little more.',
                        'code': 500
                    }}

        raw_tx = bitcoin.transaction.mktx(address_unspent, outs)
        tx = bitcoin.transaction.signall(raw_tx, address_info.private_key)
        tx_hash = bitcoin.transaction.txhash(tx)

        try:
            push_result = bitcoin.blockr_pushtx(tx)
            tx_total = sum(out.get('value') for out in outs)

            # This address has been successfully spent from, update tx info and don't check it again.
            address_info.spent = True
            address_info.spending_tx = tx_hash
            address_info.donation_amount = tx_total

            # Keep a total of all bitcoins tipped
            total_donated = DataStore.query.filter_by(key='total_donated').first()
            if total_donated:
                total_donated.value = int(int(total_donated.value) + tx_total)
            else:
                total_donated = DataStore('total_donated', tx_total)
                db.session.add(total_donated)
            db.session.commit()

            app.logger.info('Transaction successfully sent {} satoshi from {} in tx {}.'.format(tx_total, address, tx_hash))
            return {'status': 'success',
                    'data': {
                        'message': '<strong>Success!</strong> Your transaction was received and forwarded to your selected relays. '
                                    '<a target="_blank" href="https://blockchain.info/tx/'+tx_hash+'">'+tx_hash[0:10]+'..</a>',
                        'tx_hash': tx_hash
                    }}
        except Exception, err:
            if err:
                app.logger.error('Error from blockchain.info when sending tx from address {}: {}.'.format(address, str(err)))
                return {'status': 'error',
                        'message': '<strong>Blockchain.info Error:</strong> {}.'.format(err)
                        }
            else:
                app.logger.error('Unknown error when pushing forwarding tx to blockchain.info for addresss {}'.format(address))
                return {'status': 'error',
                        'message': 'There was an unknown error when trying to push the forwarding transaction to the blockchain.'
                        }

    else:
        app.logger.error('Could not find keys for addresss {} in the database'.format(address))
        return {'status': 'fail',
                'data': {
                    'message': 'Could not find the keys for this address in the database.',
                    'code': 404
                    }}

def find_unsent_payments(check_all=False):
    """
    Forward unspent transactions sent to oniontip addresses

    This function is called from the CLI to recheck recent
    addresses (< 2 hours) for any payments which the user
    may not have forwarded on the web UI. 
    """

    unspent_addresses = ForwardAddress.query.filter_by(spent=False).all()
    successful_txs = []
    for unspent in unspent_addresses:
        if ((datetime.datetime.utcnow() - unspent.created) < datetime.timedelta(hours=3)) or check_all:
            response = check_and_send(unspent.address)
            if response.get('status') == 'success':
                app.logger.info('Transaction successfully sent from CLI from {} in tx {}.'.format(unspent.address, tx_hash))
                successful_txs.append({
                    'address': unspent.address,
                    'tx_hash': response['data']['tx_hash']}
                    )
            elif response.get('status') == 'fail':
                print 'CLI Fail: {}'.format(response['data']['message'])
            elif response.get('status') == 'error':
                app.logger.error('CLI Errror: {}'.format(response['message']))
            else:
                app.logger.error('An unknown error occured in the application.')
    return successful_txs

@app.route('/forward/<address>')
def forward_from_address(address):
    '''
    Parse the results of the check_and_send function and provide the
    correct HTTP response codes for display to the user on the frontend.
    '''
    response = check_and_send(address)
    if response.get('status') == 'success':
        return Response(json.dumps(response), mimetype='application/json')
    elif response.get('status') == 'fail' or response.get('status') == 'error':
        if response.get('data'):
            response_code = response.get('data').get('code', 500)
        else:
            response_code = 500
        return Response(json.dumps(response), mimetype='application/json'), response_code
    else:
        return Response(json.dumps({'message': 'An unknown error occured in the application.'}), mimetype='application/json'), 500

def total_donated():
    total_donated = DataStore.query.filter_by(key='total_donated').first()
    return util.format_bitcoin_value(total_donated.value)
