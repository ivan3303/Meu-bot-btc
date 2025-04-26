import time
import datetime
import pandas as pd
import numpy as np
import threading
import requests
import os
from binance.client import Client

# === Configurações ===
api_key = 'P4EoHW0Zr3O0UsDjcx8SToenDPjpeZAgizy2wiBovIjmAhCg1LymcuQq7RcX7Byk'
api_secret = 'CXxgSIQ6nUHBdYOnDsDvo2g8C7ErVqjZxWNAES9bx0dCj9CvToIfFNUmtzvQZUj1'
client = Client(api_key, api_secret)

# Telegram Bot
telegram_token = '7824548048:AAFhVkyzz-kNqti-n9igud5p8B6QZkYcKz4'
chat_id = '2110910820'

# Parâmetros
symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
interval = '5m'
quantity = {
    'BTCUSDT': 0.001,
    'ETHUSDT': 0.01,
    'SOLUSDT': 1
}
take_profit_pct = 0.002  # 0.2%
stop_loss_pct = 0.0015   # 0.15%

log_filename = "log_operacoes.csv"

# Inicializar o log se não existir
if not os.path.exists(log_filename):
    pd.DataFrame(columns=['timestamp', 'symbol', 'side', 'entry_price', 'exit_price', 'result']).to_csv(log_filename, index=False)

# === Funções ===

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    data = {'chat_id': chat_id, 'text': mensagem}
    requests.post(url, data=data)

def buscar_velas(symbol, interval='5m', limit=100):
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=['open_time', 'open', 'high', 'low', 'close',
                                       'volume', 'close_time', 'quote_asset_volume',
                                       'number_of_trades', 'taker_buy_base_asset_volume',
                                       'taker_buy_quote_asset_volume', 'ignore'])
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    return df

def calcular_indicadores(df):
    df['ema3'] = df['close'].ewm(span=3, adjust=False).mean()
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['rsi'] = calcular_rsi(df['close'], 14)
    df['vol_ma'] = df['volume'].rolling(window=20).mean()
    return df

def calcular_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def checar_sinal(df):
    if df['ema3'].iloc[-2] < df['ema9'].iloc[-2] and df['ema3'].iloc[-1] > df['ema9'].iloc[-1]:
        if df['rsi'].iloc[-1] > 55 and df['volume'].iloc[-1] > df['vol_ma'].iloc[-1]:
            return 'compra'
    elif df['ema3'].iloc[-2] > df['ema9'].iloc[-2] and df['ema3'].iloc[-1] < df['ema9'].iloc[-1]:
        if df['rsi'].iloc[-1] < 45 and df['volume'].iloc[-1] > df['vol_ma'].iloc[-1]:
            return 'venda'
    return None

def executar_ordem(symbol, side, quantity):
    if side == 'BUY':
        order = client.order_market_buy(symbol=symbol, quantity=quantity)
    elif side == 'SELL':
        order = client.order_market_sell(symbol=symbol, quantity=quantity)
    return order

def registrar_operacao(symbol, side, entry_price, exit_price, result):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log = pd.read_csv(log_filename)
    novo_registro = {
        'timestamp': timestamp,
        'symbol': symbol,
        'side': side,
        'entry_price': entry_price,
        'exit_price': exit_price,
        'result': result
    }
    log = log.append(novo_registro, ignore_index=True)
    log.to_csv(log_filename, index=False)

def monitorar_resultado(symbol, preco_entrada, lado):
    while True:
        time.sleep(5)
        ticker = client.get_symbol_ticker(symbol=symbol)
        preco_atual = float(ticker['price'])

        if lado == 'compra':
            if preco_atual >= preco_entrada * (1 + take_profit_pct):
                enviar_telegram(f"✅ [{symbol}] GREEN! Preço final: {preco_atual:.2f} USDT")
                registrar_operacao(symbol, 'buy', preco_entrada, preco_atual, 'Green')
                return
            elif preco_atual <= preco_entrada * (1 - stop_loss_pct):
                enviar_telegram(f"❌ [{symbol}] RED! Preço final: {preco_atual:.2f} USDT")
                registrar_operacao(symbol, 'buy', preco_entrada, preco_atual, 'Red')
                return
        elif lado == 'venda':
            if preco_atual <= preco_entrada * (1 - take_profit_pct):
                enviar_telegram(f"✅ [{symbol}] GREEN! Preço final: {preco_atual:.2f} USDT")
                registrar_operacao(symbol, 'sell', preco_entrada, preco_atual, 'Green')
                return
            elif preco_atual >= preco_entrada * (1 + stop_loss_pct):
                enviar_telegram(f"❌ [{symbol}] RED! Preço final: {preco_atual:.2f} USDT")
                registrar_operacao(symbol, 'sell', preco_entrada, preco_atual, 'Red')
                return

def gerar_relatorio():
    if not os.path.exists(log_filename):
        return
    log = pd.read_csv(log_filename)
    hoje = datetime.datetime.now().strftime('%Y-%m-%d')
    log_hoje = log[log['timestamp'].str.contains(hoje)]

    if log_hoje.empty:
        enviar_telegram("Nenhuma operação realizada hoje.")
        return

    total_trades = len(log_hoje)
    greens = len(log_hoje[log_hoje['result'] == 'Green'])
    reds = len(log_hoje[log_hoje['result'] == 'Red'])
    winrate = (greens / total_trades) * 100

    resumo = f"""
📈 Relatório Diário [{hoje}]
- Operações: {total_trades}
- Greens: {greens}
- Reds: {reds}
- Winrate: {winrate:.2f}%
    """
    enviar_telegram(resumo)

def trader(symbol):
    while True:
        agora = datetime.datetime.now()
        if agora.minute % 5 == 0 and agora.second == 0:
            df = buscar_velas(symbol)
            df = calcular_indicadores(df)
            sinal = checar_sinal(df)

            if sinal:
                lado_ordem = 'BUY' if sinal == 'compra' else 'SELL'
                enviar_telegram(f"⚡ [{symbol}] NOVA OPERAÇÃO: {sinal.upper()}")
                
                ordem = executar_ordem(symbol, lado_ordem, quantity[symbol])
                preco_entrada = float(ordem['fills'][0]['price'])
                
                enviar_telegram(f"Preço de entrada {symbol}: {preco_entrada:.2f} USDT")
                monitorar_resultado(symbol, preco_entrada, sinal)
                
            time.sleep(300)
        time.sleep(1)

def scheduler_relatorio():
    while True:
        agora = datetime.datetime.now()
        if agora.hour == 23 and agora.minute == 59:
            gerar_relatorio()
            time.sleep(60)  # Espera 1 minuto para não enviar de novo
        time.sleep(10)

# === Inicializar o Bot ===
threads = []

# Threads dos traders
for symbol in symbols:
    t = threading.Thread(target=trader, args=(symbol,))
    t.start()
    threads.append(t)

# Thread do relatorio
t_relatorio = threading.Thread(target=scheduler_relatorio)
t_relatorio.start()
threads.append(t_relatorio)
