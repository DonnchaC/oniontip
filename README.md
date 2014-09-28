OnionTip
=========

Allows users to send tips with Bitcoin to volunteers who run Tor relays and provide Bitcoin addresses in their torrc file/router descriptor (contact and X-bitcoin fields). OnionTip uses router bandwidth measurements to allow users to donate to volunteers in a way that is proportional to the bandwidth that their routers contribute to the network.

This project is a rough implementation of the [Flattor](https://lists.torproject.org/pipermail/tor-talk/2013-August/029419.html) proposal made by George Kadianakis on the tor-talk mailing list. 

[![tip for next commit](https://tip4commit.com/projects/847.svg)](https://tip4commit.com/github/DonnchaC/oniontip)

### Running

Bitcoin addresses are generated from a secret master seed. This secure random seed should be set in the 'BITCOIN_KEY_SEED' enviroment variable before running the application. Be sure to keep a copy of the key stored securely or funds may be lost.

    $ export BITCOIN_KEY_SEED=`openssl rand 16 -hex`
    $ python main.py

The application retrieves updated lists of router bandwidth data and server descriptors from the onionoo service and the directory authorities respectively. The following is an example set of cron jobs to keep the router list and bitcoin payouts up to date.

    0 * * * * /var/www/oniontip.donncha.is/main.py --download
    0,30 * * * * /var/www/oniontip.donncha.is/main.py --check

### Notice
This project was developed at the **Dublin Bitcoin Hackathon**, July 2014 and is beta software. It likely contains bugs and it may be risky sending non-negligible donations. All bitcoin addresses are generated from a master seed and transactions are forwarded as soon as possible to minimise threats of theft or loss.

If you find any bugs or experience problems with or your transactions please submit an issue on Github or email me at donncha@donncha.is.

### License
Licensed under MIT License
(c) 2014 Donncha O'Cearbhaill

This codebase is derived heavily from the Compass tool which allows the filtering and aggregation of data about Tor relays.
(c) Sathyanarayanan Gunasekaran, The Tor Project
