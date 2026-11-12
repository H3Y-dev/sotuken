import http.client
import json
import tempfile
import os
import socket
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pc_api.owner import Owner, OwnerConflict, OwnerLock


class OwnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.receiver = Mock()
        self.receiver.pairing_status.return_value = None
        self.info = dict(running=True, server=self.receiver, thread=None,
                         url='http://192.168.1.2:8765', external_process=False)
        self.init = patch('pc_api.owner.init_receiver_for_app', return_value=self.info).start()
        self.addCleanup(patch.stopall)
        self.owner = Owner(Path(self.tmp.name)/'manager.db', Path(self.tmp.name)/'incoming', port=0)
        self.owner.start()
        self.addCleanup(self.owner.stop)

    def request(self, method='GET', path='/internal/status', headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.owner.port, timeout=2)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        return response.status, body

    def auth(self):
        return {'X-Internal-Token': self.owner.internal_key}

    def test_key_required(self):
        for headers in ({}, {'X-Internal-Token': 'wrong'}, {'X-Sotuken-Token': self.owner.internal_key}):
            self.assertEqual(self.request(headers=headers)[0], 401)

    def test_host_origin_and_forwarding_rejected(self):
        for extra in ({'Host':'localhost:8767'}, {'Origin':'null'}, {'Origin':''}, {'Forwarded':'host=evil'}):
            self.assertEqual(self.request(headers=self.auth() | extra)[0], 403)

    def test_non_loopback_rejected(self):
        with patch('pc_api.owner.ipaddress.ip_address') as address:
            address.return_value.is_loopback = False
            self.assertEqual(self.request(headers=self.auth())[0], 403)

    def test_pairing_relay(self):
        self.assertEqual(self.request('POST', '/internal/pairing', self.auth())[0], 200)
        self.receiver.start_pairing.assert_called_once_with(self.info['url'])
        self.receiver.pairing_status.return_value = {'payload': {'url':self.info['url'], 'expires_at':123}, 'remaining':10}
        self.receiver.pairing_payload.return_value = 'SOTUKEN-PAIR:example'
        status, body = self.request(path='/internal/pairing', headers=self.auth())
        self.assertEqual(status, 200)
        self.assertEqual(body['payload'], 'SOTUKEN-PAIR:example')
        self.assertEqual(self.request('POST', '/internal/pairing', self.auth())[0], 409)
        self.assertEqual(self.request('DELETE', '/internal/pairing', self.auth())[0], 200)
        self.receiver.cancel_pairing.assert_called()

    def test_url_change_cancels(self):
        self.receiver.pairing_status.return_value = {'payload':{'url':'http://192.168.1.3:8765'}, 'remaining':10}
        self.assertFalse(self.request(path='/internal/pairing', headers=self.auth())[1]['active'])
        self.receiver.cancel_pairing.assert_called_once()

    def test_duplicate_lock_and_release(self):
        lock = OwnerLock(self.owner.db_path, self.owner.incoming)
        with self.assertRaises(OwnerConflict):
            lock.acquire()
        self.owner.stop()
        lock.acquire()
        lock.release()

    def test_shutdown_joins_and_orders(self):
        events = []
        self.owner.usb = Mock()
        self.owner.usb.stop.side_effect = lambda **kw: events.append('usb')
        self.receiver.shutdown.side_effect = lambda: events.append('receiver')
        thread = self.owner.thread
        self.owner.stop()
        self.assertFalse(thread.is_alive())
        self.assertEqual(events, ['usb', 'receiver'])
        self.receiver.server_close.assert_called_once()

    def test_external_receiver_refused(self):
        self.owner.stop()
        self.info.update(server=None, external_process=True)
        with self.assertRaisesRegex(OwnerConflict, 'run_pc'):
            self.owner.start()
        self.receiver.shutdown.assert_called_once()

    def test_run_pc_same_process_and_cleanup(self):
        self.owner.stop()
        previous = Path.cwd()
        try:
            os.chdir(self.tmp.name)
            with patch('run_pc.main', side_effect=SystemExit(0)) as main:
                with self.assertRaises(SystemExit):
                    self.owner.run()
        finally:
            os.chdir(previous)
        main.assert_called_once()
        self.assertIsNone(self.owner.httpd)

    def test_idle_client_does_not_block_shutdown(self):
        client = socket.create_connection(('127.0.0.1', self.owner.port))
        self.addCleanup(client.close)
        thread = self.owner.thread
        self.owner.stop()
        self.assertFalse(thread.is_alive())

    def test_usb_initialized_once_and_stopped(self):
        self.owner.stop()
        self.owner.usb_enabled = True
        service = Mock()
        service.status.return_value = {'running':True}
        with patch('pc_api.owner.init_usb_pull_for_app', return_value=service) as init:
            self.owner.start()
            status, body = self.request(headers=self.auth())
            self.assertEqual(status, 200)
            self.assertTrue(body['usb']['running'])
            init.assert_called_once_with(incoming_dir=str(self.owner.incoming))
            self.owner.stop()
        service.stop.assert_called_once_with(timeout=None)

    def test_management_bind_failure_does_not_start_receiver(self):
        other = Owner(Path(self.tmp.name)/'other.db', Path(self.tmp.name)/'other', port=self.owner.port)
        self.addCleanup(other.stop)
        self.init.reset_mock()
        with self.assertRaises(OSError):
            other.start()
        self.init.assert_not_called()
        lock = OwnerLock(other.db_path, other.incoming)
        lock.acquire()
        lock.release()


if __name__ == '__main__':
    unittest.main()
