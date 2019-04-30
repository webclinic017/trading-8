# 3rd party
import pandas as pd

# custom
from commons import (
    setup_logging,
)


class Backtester():
    def __init__(self, signals, price_label='close', init_capital=10000, logger=None, debug=False, 
                 position_sizer=None, stop_loss=False):
        """
        *signals* - dictionary with symbols (key) and dataframes (values) with pricing data and enter/exit signals. 
        Column names for signals  are expected to be: entry_long, exit_long, entry_short, exit_short. Signals should 
        be bianries (0,1). If strategy is long/short only just insert 0 for the column.

        *price_label* - column name for the price which should be used in backtest
        """
        self.log = setup_logging(logger=logger, debug=debug)
        self.signals = self._prepare_signal(signals)
        self.position_sizer = position_sizer
        self.price_label = price_label
        self.init_capital = init_capital
        self.stop_loss = stop_loss

    def run(self, test_days=None):
        self._reset_backtest_state()

        self.log.debug('Starting backtest. Initial capital:{}, Available symbols: {}'.format(
            self._available_money, list(self.signals.keys())
        ))

        symbols_in_day = {}
        for sym_n, sym_v in self.signals.items():
            for ds in sym_v[self.price_label].keys():
                if ds in symbols_in_day:
                    symbols_in_day[ds].append(sym_n)
                else:
                    symbols_in_day[ds] = [sym_n]
        days = sorted(symbols_in_day.keys())
        
        if test_days:
            days = days[:test_days]

        for idx, ds in enumerate(days):
            self.log.debug('['+15*'-'+str(ds)[0:10]+15*'-'+']')
            self.log.debug('\tSymbols available in given session: ' + str(symbols_in_day[ds]))

            owned_shares = list(self._owned_shares.keys())
            self.log.debug('\t[-- SELL START --]')
            if len(owned_shares) == 0:
                self.log.debug('\t\tNo shares owned. Nothing to sell.')
            else:
                self.log.debug(
                    '\tOwned shares: ' + ', '.join('{}={}'.format(s, int(self._owned_shares[s]['cnt'])) 
                        for s in sorted(owned_shares))
                )
            for symbol in owned_shares:
                # safe check if missing ds for given owned symbol
                if not symbol in symbols_in_day[ds]:
                    continue
                current_sym_prices = self.signals[symbol][self.price_label]
                self.log.debug('\t+ Checking exit signal for: ' + symbol)
                if self.signals[symbol]['exit_long'][ds] == 1:
                    self.log.debug('\t\t EXIT LONG')
                    self._sell(symbol, current_sym_prices, ds, 'long')
                elif self.signals[symbol]['exit_short'][ds] == 1:
                    self.log.debug('\t\t EXIT SHORT')
                    self._sell(symbol, current_sym_prices, ds, 'short')
                elif self.stop_loss == True:
                    stop_loss_price = self.signals[symbol]['stop_loss'][ds]
                    trade_type = self._trades[self._owned_shares[symbol]['trx_id']]['type'] 
                    if (trade_type == 'long') and (current_sym_prices[ds] <= stop_loss_price):
                        self.log.debug('\t\t LONG STOP LOSS TRIGGERED - EXITING')
                        self._sell(symbol, current_sym_prices, ds, 'long')
                    elif (trade_type == 'short') and (current_sym_prices[ds] >= stop_loss_price):
                        self.log.debug('\t\t SHORT STOP LOSS TRIGGERED - EXITING')
                        self._sell(symbol, current_sym_prices, ds, 'short')
                else:
                    self.log.debug('\t+ Not exiting from: ' + symbol)
            
            if self._available_money < 0:
                raise ValueError(
                    "Account bankrupted! Money after sells is: {}. Backtester cannot run anymore!".format(
                        self._available_money
                    ))

            self.log.debug('\t[-- SELL END --]')
            self.log.debug('\t[-- BUY START --]')
            purchease_candidates = []
            for sym in symbols_in_day[ds]:
                if self.signals[sym]['entry_long'][ds] == 1:
                    purchease_candidates.append(self._define_candidate(sym, ds, 'long'))
                elif self.signals[sym]['entry_short'][ds] == 1:
                    purchease_candidates.append(self._define_candidate(sym, ds, 'short'))
            if purchease_candidates == []:
                self.log.debug('\t\tNo candidates to buy.')
            else:
                self.log.debug('\tCandidates to buy: {}'.format([c['symbol'] for c in purchease_candidates]))

            capital_at_time = self._available_money + self._calculate_account_value(ds) + self._get_money_from_short()
            symbols_to_buy = self.position_sizer.decide_what_to_buy(
                self._available_money*1.0,  # multplication is to create new object instead of using actual pointer
                purchease_candidates,
                capital = capital_at_time
            )

            for trx_details in symbols_to_buy:
                self._buy(trx_details, ds)
            self.log.debug('\t[--  BUY END --]')

            self._summarize_day(ds)

        return self._run_output(), self._trades

    def _prepare_signal(self, signals):
        """Converts to expected dictionary form."""
        _signals = signals.copy()
        for k, v in signals.items():
            _signals[k] = v.to_dict()
        return _signals

    def _reset_backtest_state(self):
        """Resets all attributes used during backtest run."""
        self._owned_shares = {}
        self._available_money = self.init_capital
        self._money_from_short = {}
        self._trades = {}
        self._account_value = {}
        self._net_account_value = {}
        self._rate_of_return = {}
        self._backup_close_prices = {}

    def _sell(self, symbol, prices, ds, exit_type):
        """Selling procedure"""
        price = prices[ds]
        shares_count = self._owned_shares[symbol]['cnt']
        fee = self.position_sizer.calculate_fee(abs(shares_count)*price)
        trx_value = (abs(shares_count)*price)
        
        trx_id = self._owned_shares[symbol]['trx_id']

        self.log.debug('\t\tSelling {} (Transaction id: {})'.format(symbol, trx_id))
        self.log.debug('\t\t\tNo. of sold shares: ' + str(int(shares_count)))
        self.log.debug('\t\t\tSell price: ' + str(price))
        self.log.debug('\t\t\tFee: ' + str(fee))
        self.log.debug('\t\t\tTransaction value (no fee): ' + str(trx_value))
        self.log.debug('\t\t\tTransaction value (gross): ' + str(trx_value - fee))

        buy_trx_value_with_fee = self._trades[trx_id]['trx_value_with_fee']
        
        if exit_type == 'long':
            sell_trx_value_with_fee = trx_value - fee
            profit = sell_trx_value_with_fee - buy_trx_value_with_fee
            self._available_money += sell_trx_value_with_fee
        elif exit_type == 'short':
            sell_trx_value_with_fee = trx_value + fee
            profit = buy_trx_value_with_fee - sell_trx_value_with_fee
            self._available_money += self._money_from_short[trx_id]
            self._money_from_short.pop(trx_id)
            self._available_money -= sell_trx_value_with_fee
  
        self.log.debug('\t\tAvailable money after selling: ' + str(self._available_money))
        
        self._trades[trx_id].update({
            'sell_ds': ds,
            'sell_value_no_fee': trx_value,
            'sell_value_with_fee': sell_trx_value_with_fee,
            'profit': round(profit, 2)
        })
        self._owned_shares.pop(symbol)

    def _buy(self, trx, ds):
        """Buying procedure"""
        if self._owned_shares.get(trx['symbol']):
            raise ValueError(
                'Trying to buy {} of {}. You currenlty own this symbol.\
                Buying additional/partial selling is currently not supported'.format(
                    trx['entry_type'], trx['symbol']
                )
            )

        trx_id = '_'.join((str(ds)[:10], trx['symbol'], trx['entry_type']))
        self.log.debug('\t\tBuying {} (Transaction id: {})'.format(trx['symbol'], trx_id))
        
        if trx['entry_type'] == 'long':
            trx_value_with_fee = trx['trx_value'] + trx['fee'] # i need to spend
            self._owned_shares[trx['symbol']] = {'cnt': trx['shares_count']}
            self._available_money -= trx_value_with_fee
                    
        elif trx['entry_type'] == 'short':
            trx_value_with_fee = trx['trx_value'] - trx['fee'] # i will get
            self._owned_shares[trx['symbol']] = {'cnt': -trx['shares_count']}
            self._available_money -= trx['fee']
            self._money_from_short[trx_id] = trx['trx_value']

        self._available_money = round(self._available_money, 2)

        self._owned_shares[trx['symbol']]['trx_id'] = trx_id
        self._trades[trx_id] = {
            'buy_ds': ds,
            'type': trx['entry_type'],
            'trx_value_no_fee': trx['trx_value'],
            'trx_value_with_fee': trx_value_with_fee,
        }

        self.log.debug('\t\t\tNo. of bought shares: ' + str(int(trx['shares_count'])))
        self.log.debug('\t\t\tBuy price: ' + str(trx['price']))
        self.log.debug('\t\t\tFee: ' + str(trx['fee']))
        self.log.debug('\t\t\tTransaction value (no fee): ' + str(trx['trx_value']))
        self.log.debug('\t\t\tTransaction value (gross): ' + str(trx_value_with_fee))
        self.log.debug('\t\tAvailable money after buying: ' + str(self._available_money))
        if trx['entry_type'] == 'short':
            self.log.debug('\t\tMoney from short sell: ' + str(self._money_from_short[trx_id]))

    def _define_candidate(self, symbol, ds, entry_type):
        """Reutrns dictionary with purchease candidates and necessery keys."""
        return {
            'symbol': symbol,
            'entry_type': entry_type,
            'price': self.signals[symbol][self.price_label][ds]
        }

    def _calculate_account_value(self, ds):
        _account_value = 0
        for symbol, vals in self._owned_shares.items():
            try:
                price = self.signals[symbol][self.price_label][ds]
            except KeyError:
                # in case of missing ds in symbol take previous price value
                price, price_ds = self._backup_close_prices[symbol]
                self.log.warning('\t\t!!! Using backup price from {} for {} as there was no data for it at {} !!!'.format(
                    price_ds, symbol, ds
                ))
            _account_value += vals['cnt'] * price
            self._backup_close_prices[symbol] = (price, ds)
        return _account_value

    def _get_money_from_short(self):
        return sum([m for m in self._money_from_short.values()])

    def _summarize_day(self, ds):
        """Sets up summaries after finished session day."""
        self.log.debug('[ SUMMARIZE SESSION {} ]'.format(str(ds)[:10]))
        _account_value = self._calculate_account_value(ds)
        # account value (can be negative) + avaiable money + any borrowed moneny
        nav = _account_value + self._available_money + self._get_money_from_short()
        self._account_value[ds] = _account_value
        self._net_account_value[ds] = nav
        self._rate_of_return[ds] = ((nav-self.init_capital)/self.init_capital)*100

        self.log.debug('Available money is: ' + str(self._available_money))
        self.log.debug('Shares: ' + ', '.join(sorted(['{}: {}'.format(k, v['cnt']) for k,v in self._owned_shares.items()])))
        self.log.debug('Net Account Value is: ' + str(nav))
        self.log.debug('Rate of return: ' + str(self._rate_of_return[ds]))

    def _run_output(self):
        """
        Aggregates results from backtester run and outputs it as a DataFrame
        """
        df = pd.DataFrame()
        idx = list(self._account_value.keys())
        results = (
            (self._account_value, 'account_value'),
            (self._net_account_value, 'nav'),
            (self._rate_of_return, 'rate_of_return')
        )
        for d, col in results:
            temp_df = pd.DataFrame(list(d.items()), index=idx, columns=['ds', col])
            temp_df.drop('ds', axis=1, inplace=True)
            df = pd.concat([df, temp_df], axis=1)
        return df
