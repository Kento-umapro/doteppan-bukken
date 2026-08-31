#!/usr/bin/env python3
"""AWS Cognito USER_SRP_AUTH を純Python(標準ライブラリ)＋curlで実行し、アクセストークンを得る。

pycognito/boto3 が使えない環境(cryptography native壊れ)向けの自己完結SRP実装。
HTTPは環境のプロキシCAを使うcurl経由。外部依存なし。

使い方:
    from cognito_srp import srp_login
    tok = srp_login(pool_id, client_id, username, password, region='ap-northeast-1')
    # tok['AccessToken'] / tok['IdToken'] / tok['RefreshToken']
"""
import hashlib, hmac, os, base64, datetime, json, subprocess, re

CA = "/root/.ccr/ca-bundle.crt"

N_HEX = (
    'FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1'
    '29024E088A67CC74020BBEA63B139B22514A08798E3404DD'
    'EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245'
    'E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED'
    'EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D'
    'C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F'
    '83655D23DCA3AD961C62F356208552BB9ED529077096966D'
    '670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B'
    'E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9'
    'DE2BCBF6955817183995497CEA956AE515D2261898FA0510'
    '15728E5A8AAAC42DAD33170D04507A33A85521ABDF1CBA64'
    'ECFB850458DBEF0A8AEA71575D060C7DB3970F85A6E1E4C7'
    'ABF5AE8CDB0933D71E8C94E04A25619DCEE3D2261AD2EE6B'
    'F12FFA06D98A0864D87602733EC86A64521F2B18177B200C'
    'BBE117577A615D6C770988C0BAD946E208E24FA074E5AB31'
    '43DB5BFCE0FD108E4B82D120A93AD2CAFFFFFFFFFFFFFFFF')
N = int(N_HEX, 16)
G = 2
INFO_BITS = b'Caldera Derived Key'


def _hash(b):
    a = hashlib.sha256(b).hexdigest()
    return '0' * (64 - len(a)) + a


def _hex_hash(h):
    return _hash(bytes.fromhex(h))


def _pad(h):
    if isinstance(h, int):
        h = format(h, 'x')
    if len(h) % 2 == 1:
        h = '0' + h
    elif h[0] in '89abcdefABCDEF':
        h = '00' + h
    return h


def _hkdf(ikm, salt):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, INFO_BITS + bytes([1]), hashlib.sha256).digest()[:16]


def _post(region, target, body):
    out = subprocess.run(
        ['curl', '-sS', '--max-time', '30', '--cacert', CA, '-X', 'POST',
         f'https://cognito-idp.{region}.amazonaws.com/',
         '-H', 'Content-Type: application/x-amz-json-1.1',
         '-H', 'X-Amz-Target: AWSCognitoIdentityProviderService.' + target,
         '-d', json.dumps(body)],
        capture_output=True, text=True).stdout
    return json.loads(out)


def srp_login(pool_id, client_id, username, password, region='ap-northeast-1'):
    pool_name = pool_id.split('_', 1)[1]
    k = int(_hex_hash('00' + N_HEX + '0' + format(G, 'x')), 16)
    while True:
        a = int.from_bytes(os.urandom(128), 'big') % N
        A = pow(G, a, N)
        if A % N != 0:
            break

    r1 = _post(region, 'InitiateAuth', {
        'AuthFlow': 'USER_SRP_AUTH', 'ClientId': client_id,
        'AuthParameters': {'USERNAME': username, 'SRP_A': format(A, 'x')}})
    if 'ChallengeName' not in r1:
        raise RuntimeError('InitiateAuth: ' + json.dumps(r1, ensure_ascii=False)[:200])
    cp = r1['ChallengeParameters']
    B = int(cp['SRP_B'], 16)
    salt = cp['SALT']
    secret_block = cp['SECRET_BLOCK']
    user_id = cp['USER_ID_FOR_SRP']

    u = int(_hex_hash(_pad(A) + _pad(B)), 16)
    id_hash = _hash((pool_name + user_id + ':' + password).encode('utf-8'))
    x = int(_hex_hash(_pad(salt) + id_hash), 16)
    s = pow(B - k * pow(G, x, N), a + u * x, N)
    hkdf = _hkdf(bytes.fromhex(_pad(s)), bytes.fromhex(_pad(u)))

    ts = datetime.datetime.utcnow().strftime('%a %b %-d %H:%M:%S UTC %Y')
    msg = (pool_name + user_id).encode('utf-8') + base64.b64decode(secret_block) + ts.encode('utf-8')
    sig = base64.b64encode(hmac.new(hkdf, msg, hashlib.sha256).digest()).decode()

    r2 = _post(region, 'RespondToAuthChallenge', {
        'ChallengeName': 'PASSWORD_VERIFIER', 'ClientId': client_id,
        'ChallengeResponses': {
            'USERNAME': user_id, 'PASSWORD_CLAIM_SECRET_BLOCK': secret_block,
            'PASSWORD_CLAIM_SIGNATURE': sig, 'TIMESTAMP': ts}})
    if r2.get('ChallengeName'):
        raise RuntimeError('追加チャレンジ(' + r2['ChallengeName'] + ') が必要です')
    if 'AuthenticationResult' not in r2:
        raise RuntimeError('RespondToAuthChallenge: ' + json.dumps(r2, ensure_ascii=False)[:200])
    return r2['AuthenticationResult']


if __name__ == '__main__':
    import sys
    pool = os.environ.get('LEADLENS_POOL', 'ap-northeast-1_m6RP7KvHC')
    client = os.environ.get('LEADLENS_CLIENT', '7ek32ebdlid2o5i84bsikocug7')
    u, p = os.environ.get('LEADLENS_USER'), os.environ.get('LEADLENS_PASS')
    if not u or not p:
        print('LEADLENS_USER / LEADLENS_PASS を環境変数で渡してください'); sys.exit(1)
    t = srp_login(pool, client, u, p)
    print('AccessToken 文字数', len(t['AccessToken']), '/ 期限(秒)', t.get('ExpiresIn'))
