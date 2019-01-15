# built in
import csv
import os
import time

# 3rd party
import pandas as pd
import numpy as np

# custom
from price_collector import PriceCollector


class GPWData():
    def __init__(self, pricing_data_path='./pricing_data'):
        self.pricing_data_path = pricing_data_path
        self.collector = PriceCollector()
        self.column_names = ['date', 'open', 'high', 'low', 'close', 'volume']

    def download_data_to_csv(self, symbols=None):
        """
        Collects historical data and outputs csv file in *pricing_data_path*. Currently it takes
        full history until execution and its overwriting files.
        """
        for symbol in symbols:
            print('Downloading {}'.format(symbol))
            pricing_data = self.collector.get_historical_data(symbol)
            with open(self._output_path(symbol), 'w') as fh:
                writer = csv.writer(fh)
                writer.writerow(self.column_names)
                for date, prices in pricing_data.items():
                    writer.writerow([date] + prices)
            time.sleep(0.5)

    def load(self, symbols=None, df=True, from_csv=True):
        """
        Returns pricing data for *symbols*. It may be single symbol as a string or iterable with symbols.
        If *from_csv* is True it reads data from csv, else it gets it from the web. Currently it takes
        full history until execution.
        Ouput is pandas DataFrame or list of lists with ['date','open','high','low','close','volume']
        if only 1 symbol is provided. If more symbols requested then the output will be a dictionary with 
        symbol as a key and data with the same format as the one for single symbol.
        """
        if isinstance(symbols, str):
            symbols = [symbols]
        pricing_data = {}
        for symbol in symbols:
            if from_csv:
                with open(self._output_path(symbol), 'r') as fh:
                    reader = csv.reader(fh)
                    next(reader)  # skip the header
                    data = [
                        [row[0], float(row[1]), float(row[2]), float(row[3]), float(row[4]), int(row[5])]
                        for row in reader
                    ]
            else:
                data_dict = self.collector.get_historical_data(symbol)
                data = [[date] + prices for date, prices in data_dict.items()]
            # load to DataFrame to fill missing data-points
            date_col = self.column_names[0]
            data = pd.DataFrame(data, columns=self.column_names)
            data.replace(to_replace=0, value=np.nan, inplace=True)
            data.fillna(method='ffill', inplace=True)
            # (back) to desired output format
            if df:
                data.name=symbol
                data.set_index(pd.DatetimeIndex(data[date_col]), inplace=True)
                data.drop(date_col, axis=1, inplace=True)
            else:
                data = data.values.tolist()
            pricing_data[symbol] = data
        if len(symbols) == 1:
            return pricing_data[symbol]
        else:
            return pricing_data

    def _output_path(self, symbol):
        return os.path.join(self.pricing_data_path, '{}_pricing.csv'.format(symbol))



def main():
    gpw_data = GPWData()
    # WIG20 symbols
    wig20_symbols = [
        'ALIOR',
        'ASSECOPOL',
        'SANPL',
        'CCC',
        'CYFRPLSAT',
        'ENEA',
        'ENERGA',
        'EUROCASH',
        'KGHM',
        'LOTOS',
        'LPP',
        'MBANK',
        'ORANGEPL',
        'PEKAO',
        'PGE',
        'PGNIG',
        'PKNORLEN',
        'PKOBP',
        'PZU',
        'TAURONPE'
    ]
    # gpw_data.download_data_to_csv(symbols=wig20_symbols)
    data = gpw_data.load(symbols='SANPL')
    # data = gpw_data.load(symbols=['SANPL', 'ALIOR'])
    print(data)

    etfs_symbols = list(PriceCollector().get_etfs_symbols().keys())
    gpw_data.download_data_to_csv(symbols=etfs_symbols)



if __name__ == '__main__':
    main()