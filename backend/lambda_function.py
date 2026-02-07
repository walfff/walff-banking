"""
🏦 Mini Banco Lambda v2 — Cognito + PIX
=========================================
Rotas ajustadas para o API Gateway configurado.
"""

import json
import boto3
import uuid
import os
import re
import string
import random
from datetime import datetime, timezone
from decimal import Decimal

# Inicialização fora do handler
dynamodb = boto3.resource('dynamodb')

ACCOUNTS_TABLE = os.environ.get('ACCOUNTS_TABLE', 'mini-banco-contas')
TRANSACTIONS_TABLE = os.environ.get('TRANSACTIONS_TABLE', 'mini-banco-transacoes')
PIX_KEYS_TABLE = os.environ.get('PIX_KEYS_TABLE', 'mini-banco-pix-keys')

accounts_table = dynamodb.Table(ACCOUNTS_TABLE)
transactions_table = dynamodb.Table(TRANSACTIONS_TABLE)
pix_keys_table = dynamodb.Table(PIX_KEYS_TABLE)


def lambda_handler(event, context):
    print(f"📨 Evento: {json.dumps(event, default=str)}")

    http_method = event.get('httpMethod', '')
    path = event.get('path', '')

    try:
        # ══════════════════════════════════════
        # Rotas públicas (sem autenticação)
        # ══════════════════════════════════════
        if path == '/health' and http_method == 'GET':
            return resposta(200, {
                'status': 'ok',
                'servico': 'Mini Banco Lambda v2 🏦',
                'versao': '2.0 — Cognito + PIX'
            })

        # Cadastro de conta (público — POST /auth)
        if path == '/auth' and http_method == 'POST':
            return criar_conta(event)

        # Legado v1: criar conta via /contas
        if path == '/contas' and http_method == 'POST':
            return criar_conta(event)

        # Legado v1: consultar saldo via /contas/{id}
        if path.startswith('/contas/') and http_method == 'GET':
            conta_id = event.get('pathParameters', {}).get('id', '')
            return consultar_saldo(conta_id)

        # Legado v1: extrato via /extrato/{id}
        if path.startswith('/extrato/') and http_method == 'GET':
            conta_id = event.get('pathParameters', {}).get('id', '')
            return ver_extrato_por_id(conta_id)

        # ══════════════════════════════════════
        # Rotas autenticadas
        # ══════════════════════════════════════
        user_id = extrair_user_id(event)
        if not user_id:
            return resposta(401, {'erro': 'Não autorizado. Faça login primeiro.'})

        # Minha conta
        if path == '/minha-conta' and http_method == 'GET':
            return minha_conta(user_id)

        # Cadastro de conta (para ver detalhes no GET /cadastro)
        if path == '/cadastro' and http_method == 'GET':
            return minha_conta(user_id)

        # Depositar
        if path == '/depositar' and http_method == 'POST':
            return depositar(event, user_id)

        # Sacar
        if path == '/sacar' and http_method == 'POST':
            return sacar(event, user_id)

        # Transferir (legado v1)
        if path == '/transferir' and http_method == 'POST':
            return transferir_legado(event)

        # Extrato (autenticado, sem ID)
        if path == '/extrato' and http_method == 'GET':
            return ver_extrato(user_id)

        # ── PIX ──
        # Chaves PIX
        if path == '/pix/chaves' and http_method == 'POST':
            return registrar_chave_pix(event, user_id)

        if path == '/pix/chaves' and http_method == 'GET':
            return listar_chaves_pix(user_id)

        if path == '/pix/chaves' and http_method == 'DELETE':
            return remover_chave_pix(event, user_id)

        # Buscar destinatário por chave
        if path == '/pix/buscar' and http_method == 'POST':
            return buscar_por_chave_pix(event)

        # Enviar PIX
        if path == '/pix/enviar' and http_method == 'POST':
            return transferir_pix(event, user_id)

        return resposta(404, {'erro': f'Rota não encontrada: {http_method} {path}'})

    except Exception as e:
        print(f"❌ Erro: {str(e)}")
        import traceback
        traceback.print_exc()
        return resposta(500, {'erro': 'Erro interno do servidor', 'detalhes': str(e)})


# ══════════════════════════════════════
# 🔐 AUTENTICAÇÃO
# ══════════════════════════════════════

def extrair_user_id(event):
    """Extrai user_id do Cognito (JWT) ou do header X-User-Id (modo teste)."""
    try:
        # Via Cognito Authorizer (quando authorizer está aplicado nas rotas)
        claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
        user_id = claims.get('sub')
        if user_id:
            return user_id

        # Via header Authorization (decodifica JWT diretamente)
        headers = event.get('headers', {}) or {}
        auth_header = None
        for key in headers:
            if key.lower() == 'authorization':
                auth_header = headers[key]
                break

        if auth_header:
            # Remove "Bearer " se presente
            token = auth_header.replace('Bearer ', '').replace('bearer ', '')
            try:
                import base64
                # JWT tem 3 partes: header.payload.signature
                payload = token.split('.')[1]
                # Adiciona padding se necessário
                padding = 4 - len(payload) % 4
                if padding != 4:
                    payload += '=' * padding
                decoded = json.loads(base64.b64decode(payload))
                sub = decoded.get('sub')
                if sub:
                    print(f"✅ User ID extraído do JWT: {sub}")
                    return sub
            except Exception as e:
                print(f"⚠️ Erro ao decodificar JWT: {e}")

        # Fallback: header X-User-Id (modo teste)
        for key in headers:
            if key.lower() == 'x-user-id':
                return headers[key]

        return None
    except Exception:
        return None


# ══════════════════════════════════════
# 🏦 CONTA
# ══════════════════════════════════════

def criar_conta(event):
    """Cria conta bancária. CPF vira chave PIX automaticamente."""
    body = json.loads(event.get('body', '{}'))
    nome = body.get('nome')
    cpf = body.get('cpf')

    if not nome or not cpf:
        return resposta(400, {'erro': 'Nome e CPF são obrigatórios'})

    user_id = extrair_user_id(event)
    if not user_id:
        user_id = 'anon-' + str(uuid.uuid4())[:8]

    # Verifica se já tem conta
    conta_existente = buscar_conta_por_user(user_id)
    if conta_existente:
        return resposta(409, {
            'erro': 'Você já possui uma conta',
            'conta_id': conta_existente['conta_id']
        })

    conta_id = str(uuid.uuid4())[:8]
    agora = datetime.now(timezone.utc).isoformat()

    item = {
        'conta_id': conta_id,
        'user_id': user_id,
        'nome': nome,
        'cpf': cpf,
        'saldo': Decimal('0.00'),
        'criado_em': agora,
        'atualizado_em': agora,
        'ativo': True
    }

    accounts_table.put_item(Item=item)
    registrar_transacao(conta_id, 'ABERTURA', Decimal('0'), 'Conta criada')

    # Registra CPF como chave PIX automaticamente
    try:
        pix_keys_table.put_item(
            Item={
                'chave_valor': cpf,
                'chave_tipo': 'CPF',
                'conta_id': conta_id,
                'user_id': user_id,
                'nome_titular': nome,
                'criado_em': agora
            },
            ConditionExpression='attribute_not_exists(chave_valor)'
        )
    except Exception:
        pass

    return resposta(201, {
        'mensagem': 'Conta criada com sucesso! 🎉',
        'conta_id': conta_id,
        'nome': nome,
        'chave_pix_cpf': cpf
    })


def minha_conta(user_id):
    """Retorna conta do usuário logado com suas chaves PIX."""
    conta = buscar_conta_por_user(user_id)
    if not conta:
        return resposta(404, {'erro': 'Você ainda não tem uma conta. Crie uma primeiro!'})

    chaves = buscar_chaves_por_conta(conta['conta_id'])

    return resposta(200, {
        'conta_id': conta['conta_id'],
        'nome': conta['nome'],
        'cpf': conta.get('cpf', ''),
        'saldo': float(conta['saldo']),
        'chaves_pix': chaves,
        'criado_em': conta['criado_em'],
        'atualizado_em': conta['atualizado_em']
    })


def consultar_saldo(conta_id):
    """Legado v1: consulta saldo por conta_id."""
    conta = buscar_conta(conta_id)
    if not conta:
        return resposta(404, {'erro': 'Conta não encontrada'})
    return resposta(200, {
        'conta_id': conta['conta_id'],
        'nome': conta['nome'],
        'saldo': float(conta['saldo']),
        'atualizado_em': conta['atualizado_em']
    })


# ══════════════════════════════════════
# 💰 OPERAÇÕES
# ══════════════════════════════════════

def depositar(event, user_id):
    conta = buscar_conta_por_user(user_id)
    if not conta:
        return resposta(404, {'erro': 'Conta não encontrada'})

    body = json.loads(event.get('body', '{}'))
    valor = body.get('valor')

    if not valor or float(valor) <= 0:
        return resposta(400, {'erro': 'Valor deve ser positivo'})

    valor = Decimal(str(valor))
    conta_id = conta['conta_id']

    novo_saldo = accounts_table.update_item(
        Key={'conta_id': conta_id},
        UpdateExpression='SET saldo = saldo + :val, atualizado_em = :now',
        ExpressionAttributeValues={
            ':val': valor,
            ':now': datetime.now(timezone.utc).isoformat()
        },
        ReturnValues='ALL_NEW'
    )

    registrar_transacao(conta_id, 'DEPOSITO', valor, body.get('descricao', 'Depósito'))

    return resposta(200, {
        'mensagem': f'Depósito de R$ {float(valor):.2f} realizado! 💰',
        'saldo_atual': float(novo_saldo['Attributes']['saldo'])
    })


def sacar(event, user_id):
    conta = buscar_conta_por_user(user_id)
    if not conta:
        return resposta(404, {'erro': 'Conta não encontrada'})

    body = json.loads(event.get('body', '{}'))
    valor = body.get('valor')

    if not valor or float(valor) <= 0:
        return resposta(400, {'erro': 'Valor deve ser positivo'})

    valor = Decimal(str(valor))
    conta_id = conta['conta_id']

    if conta['saldo'] < valor:
        return resposta(400, {
            'erro': 'Saldo insuficiente 😢',
            'saldo_atual': float(conta['saldo'])
        })

    try:
        novo_saldo = accounts_table.update_item(
            Key={'conta_id': conta_id},
            UpdateExpression='SET saldo = saldo - :val, atualizado_em = :now',
            ConditionExpression='saldo >= :val',
            ExpressionAttributeValues={
                ':val': valor,
                ':now': datetime.now(timezone.utc).isoformat()
            },
            ReturnValues='ALL_NEW'
        )
    except Exception:
        return resposta(400, {'erro': 'Saldo insuficiente (verificação concorrente)'})

    registrar_transacao(conta_id, 'SAQUE', valor, body.get('descricao', 'Saque'))

    return resposta(200, {
        'mensagem': f'Saque de R$ {float(valor):.2f} realizado! 🏧',
        'saldo_atual': float(novo_saldo['Attributes']['saldo'])
    })


def transferir_legado(event):
    """Legado v1: transferência por conta_id."""
    body = json.loads(event.get('body', '{}'))
    origem_id = body.get('conta_origem')
    destino_id = body.get('conta_destino')
    valor = body.get('valor')

    if not origem_id or not destino_id or not valor:
        return resposta(400, {'erro': 'conta_origem, conta_destino e valor são obrigatórios'})

    valor = Decimal(str(valor))
    if valor <= 0:
        return resposta(400, {'erro': 'Valor deve ser positivo'})
    if origem_id == destino_id:
        return resposta(400, {'erro': 'Contas devem ser diferentes'})

    conta_origem = buscar_conta(origem_id)
    conta_destino = buscar_conta(destino_id)
    if not conta_origem:
        return resposta(404, {'erro': 'Conta de origem não encontrada'})
    if not conta_destino:
        return resposta(404, {'erro': 'Conta de destino não encontrada'})
    if conta_origem['saldo'] < valor:
        return resposta(400, {'erro': 'Saldo insuficiente'})

    agora = datetime.now(timezone.utc).isoformat()

    accounts_table.update_item(
        Key={'conta_id': origem_id},
        UpdateExpression='SET saldo = saldo - :val, atualizado_em = :now',
        ConditionExpression='saldo >= :val',
        ExpressionAttributeValues={':val': valor, ':now': agora}
    )
    accounts_table.update_item(
        Key={'conta_id': destino_id},
        UpdateExpression='SET saldo = saldo + :val, atualizado_em = :now',
        ExpressionAttributeValues={':val': valor, ':now': agora}
    )

    descricao = body.get('descricao', 'Transferência')
    registrar_transacao(origem_id, 'TRANSFERENCIA_ENVIADA', valor, f'{descricao} para {conta_destino["nome"]}')
    registrar_transacao(destino_id, 'TRANSFERENCIA_RECEBIDA', valor, f'{descricao} de {conta_origem["nome"]}')

    return resposta(200, {
        'mensagem': f'Transferência de R$ {float(valor):.2f} realizada! 🔄',
        'de': conta_origem['nome'],
        'para': conta_destino['nome'],
        'valor': float(valor)
    })


# ══════════════════════════════════════
# 🔑 CHAVES PIX
# ══════════════════════════════════════

def gerar_chave_aleatoria():
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(32))


def registrar_chave_pix(event, user_id):
    conta = buscar_conta_por_user(user_id)
    if not conta:
        return resposta(404, {'erro': 'Crie uma conta primeiro'})

    body = json.loads(event.get('body', '{}'))
    tipo = body.get('tipo', '').upper()
    valor = body.get('valor', '')

    if tipo not in ['CPF', 'EMAIL', 'TELEFONE', 'ALEATORIA']:
        return resposta(400, {'erro': 'Tipo deve ser: CPF, EMAIL, TELEFONE ou ALEATORIA'})

    if tipo == 'ALEATORIA':
        valor = gerar_chave_aleatoria()

    if not valor:
        return resposta(400, {'erro': 'Valor da chave é obrigatório'})

    # Verifica limite de 5 chaves
    chaves = buscar_chaves_por_conta(conta['conta_id'])
    if len(chaves) >= 5:
        return resposta(400, {'erro': 'Limite de 5 chaves PIX por conta'})

    agora = datetime.now(timezone.utc).isoformat()

    try:
        pix_keys_table.put_item(
            Item={
                'chave_valor': valor,
                'chave_tipo': tipo,
                'conta_id': conta['conta_id'],
                'user_id': user_id,
                'nome_titular': conta['nome'],
                'criado_em': agora
            },
            ConditionExpression='attribute_not_exists(chave_valor)'
        )
    except Exception:
        return resposta(409, {'erro': 'Esta chave PIX já está cadastrada por outra conta'})

    return resposta(201, {
        'mensagem': f'Chave PIX registrada! 🔑',
        'tipo': tipo,
        'chave': valor
    })


def listar_chaves_pix(user_id):
    conta = buscar_conta_por_user(user_id)
    if not conta:
        return resposta(404, {'erro': 'Conta não encontrada'})

    chaves = buscar_chaves_por_conta(conta['conta_id'])

    return resposta(200, {
        'conta_id': conta['conta_id'],
        'chaves': chaves
    })


def remover_chave_pix(event, user_id):
    conta = buscar_conta_por_user(user_id)
    if not conta:
        return resposta(404, {'erro': 'Conta não encontrada'})

    body = json.loads(event.get('body', '{}'))
    chave_valor = body.get('chave', '')

    if not chave_valor:
        return resposta(400, {'erro': 'Informe a chave a remover'})

    # Verifica se a chave pertence ao usuário
    chave = pix_keys_table.get_item(Key={'chave_valor': chave_valor}).get('Item')
    if not chave or chave.get('user_id') != user_id:
        return resposta(404, {'erro': 'Chave não encontrada ou não pertence a você'})

    pix_keys_table.delete_item(Key={'chave_valor': chave_valor})

    return resposta(200, {'mensagem': 'Chave PIX removida! 🗑️'})


def buscar_por_chave_pix(event):
    """Busca titular de uma chave PIX (para mostrar nome antes de confirmar)."""
    body = json.loads(event.get('body', '{}'))
    chave = body.get('chave', '').strip()

    if not chave:
        return resposta(400, {'erro': 'Informe a chave PIX'})

    resultado = pix_keys_table.get_item(Key={'chave_valor': chave})
    item = resultado.get('Item')

    if not item:
        return resposta(404, {'erro': 'Chave PIX não encontrada'})

    return resposta(200, {
        'encontrado': True,
        'nome_titular': item['nome_titular'],
        'tipo_chave': item['chave_tipo'],
        'chave': chave
    })


def transferir_pix(event, user_id):
    """Transferência via chave PIX."""
    conta_origem = buscar_conta_por_user(user_id)
    if not conta_origem:
        return resposta(404, {'erro': 'Conta de origem não encontrada'})

    body = json.loads(event.get('body', '{}'))
    chave = body.get('chave', '').strip()
    valor = body.get('valor')
    descricao = body.get('descricao', 'PIX')

    if not chave or not valor:
        return resposta(400, {'erro': 'Chave PIX e valor são obrigatórios'})

    valor = Decimal(str(valor))
    if valor <= 0:
        return resposta(400, {'erro': 'Valor deve ser positivo'})

    # Busca destinatário pela chave
    resultado_pix = pix_keys_table.get_item(Key={'chave_valor': chave})
    item_pix = resultado_pix.get('Item')

    if not item_pix:
        return resposta(404, {'erro': 'Chave PIX não encontrada'})

    conta_destino_id = item_pix['conta_id']

    if conta_destino_id == conta_origem['conta_id']:
        return resposta(400, {'erro': 'Não é possível fazer PIX para você mesmo'})

    if conta_origem['saldo'] < valor:
        return resposta(400, {
            'erro': 'Saldo insuficiente 😢',
            'saldo_atual': float(conta_origem['saldo'])
        })

    conta_destino = buscar_conta(conta_destino_id)
    if not conta_destino:
        return resposta(404, {'erro': 'Conta de destino não encontrada'})

    agora = datetime.now(timezone.utc).isoformat()

    # Debita origem
    try:
        accounts_table.update_item(
            Key={'conta_id': conta_origem['conta_id']},
            UpdateExpression='SET saldo = saldo - :val, atualizado_em = :now',
            ConditionExpression='saldo >= :val',
            ExpressionAttributeValues={':val': valor, ':now': agora}
        )
    except Exception:
        return resposta(400, {'erro': 'Saldo insuficiente (verificação concorrente)'})

    # Credita destino
    accounts_table.update_item(
        Key={'conta_id': conta_destino_id},
        UpdateExpression='SET saldo = saldo + :val, atualizado_em = :now',
        ExpressionAttributeValues={':val': valor, ':now': agora}
    )

    registrar_transacao(
        conta_origem['conta_id'], 'PIX_ENVIADO', valor,
        f'{descricao} para {conta_destino["nome"]} (chave: {chave})'
    )
    registrar_transacao(
        conta_destino_id, 'PIX_RECEBIDO', valor,
        f'{descricao} de {conta_origem["nome"]}'
    )

    # Busca saldo atualizado
    conta_atualizada = buscar_conta(conta_origem['conta_id'])

    return resposta(200, {
        'mensagem': f'PIX de R$ {float(valor):.2f} enviado! ⚡',
        'para': item_pix['nome_titular'],
        'chave': chave,
        'valor': float(valor),
        'saldo_atual': float(conta_atualizada['saldo'])
    })


# ══════════════════════════════════════
# 📋 EXTRATO
# ══════════════════════════════════════

def ver_extrato(user_id):
    conta = buscar_conta_por_user(user_id)
    if not conta:
        return resposta(404, {'erro': 'Conta não encontrada'})
    return ver_extrato_por_id(conta['conta_id'])


def ver_extrato_por_id(conta_id):
    conta = buscar_conta(conta_id)
    if not conta:
        return resposta(404, {'erro': 'Conta não encontrada'})

    from boto3.dynamodb.conditions import Key

    resultado = transactions_table.query(
        KeyConditionExpression=Key('conta_id').eq(conta_id),
        ScanIndexForward=False,
        Limit=30
    )

    transacoes = []
    for t in resultado.get('Items', []):
        transacoes.append({
            'tipo': t['tipo'],
            'valor': float(t['valor']),
            'descricao': t.get('descricao', ''),
            'data': t['data']
        })

    return resposta(200, {
        'conta_id': conta_id,
        'nome': conta['nome'],
        'saldo_atual': float(conta['saldo']),
        'transacoes': transacoes
    })


# ══════════════════════════════════════
# 🔧 AUXILIARES
# ══════════════════════════════════════

def buscar_conta(conta_id):
    resultado = accounts_table.get_item(Key={'conta_id': conta_id})
    return resultado.get('Item')


def buscar_conta_por_user(user_id):
    from boto3.dynamodb.conditions import Key
    try:
        resultado = accounts_table.query(
            IndexName='user_id-index',
            KeyConditionExpression=Key('user_id').eq(user_id)
        )
        items = resultado.get('Items', [])
        return items[0] if items else None
    except Exception as e:
        print(f"⚠️ Erro GSI user_id-index: {e}")
        from boto3.dynamodb.conditions import Attr
        resultado = accounts_table.scan(
            FilterExpression=Attr('user_id').eq(user_id)
        )
        items = resultado.get('Items', [])
        return items[0] if items else None


def buscar_chaves_por_conta(conta_id):
    from boto3.dynamodb.conditions import Attr
    try:
        resultado = pix_keys_table.scan(
            FilterExpression=Attr('conta_id').eq(conta_id)
        )
        return [
            {
                'tipo': item['chave_tipo'],
                'chave': item['chave_valor'],
                'criado_em': item.get('criado_em', '')
            }
            for item in resultado.get('Items', [])
        ]
    except Exception:
        return []


def registrar_transacao(conta_id, tipo, valor, descricao=''):
    transactions_table.put_item(Item={
        'conta_id': conta_id,
        'transacao_id': datetime.now(timezone.utc).isoformat() + '#' + str(uuid.uuid4())[:4],
        'tipo': tipo,
        'valor': valor,
        'descricao': descricao,
        'data': datetime.now(timezone.utc).isoformat()
    })


def resposta(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization,X-User-Id'
        },
        'body': json.dumps(body, ensure_ascii=False, default=str)
    }