import numpy as np
import pandas as pd
from log import log_general
from sklearn.linear_model import LinearRegression
from collections import OrderedDict

class MarketPosition:
    exit_types = ['take_profit', 'trailing_take_profit', 'true_trailing_take_profit', 'stop_loss', 'trailing_stop_loss']
    __slots__ = ['token_address', 'avg_price', 'current_price', 'position_size', 'dual_pct_adj', 'entries', 'exits'] + exit_types

    def __init__(self, txid, token_address, entry_price, position_size, unixtime):
        self.token_address : str = token_address
        self.avg_price : float = entry_price
        self.current_price : float = entry_price
        self.position_size : float = position_size
        self.entries = OrderedDict({txid: (entry_price, position_size, unixtime)})
        self.exits = OrderedDict()
        self.last_price = self.current_price
        self.highest_price = self.current_price
        self.stop_loss = []
        self.take_profit = []
        self.trailing_stop_loss = []
        self.trailing_take_profit = []
        self.true_trailing_take_profit = []

    def update(self, current_price):
        self.last_price = self.current_price
        self.current_price = current_price
        if self.current_price > self.highest_price:
            self.highest_price = self.current_price
        return self._advise()

    def confirm(self, exits):
        exit_amt = 0
        impacted = {key: 0 for key in self.exit_types}
        # exits is of form exit = {txid : (exit_type, exit_pct, exit_condition_index)}
        for txid, vals in exits.items():
            if vals[0] in self.exit_types:
                getattr(self, vals[0]).pop(vals[2])
                exit = (vals[0], vals[1])
                self.exits[txid] = exit
                impacted[vals[0]] += vals[1]
                exit_amt += vals[1]
                if exit_amt >= 1:
                    return 0
        self.position_size -= self.position_size * exit_amt
        impacted = {k: v for k, v in impacted.items() if v != 0}
        self._adjust_exit_sizes(impacted)
        return 1 - exit_amt

    def _adjust_exit_sizes(self, impacted):
        for exit_type, pct_exit in impacted.items():
            exit_list = getattr(self, exit_type)
            if not exit_list:
                continue
            current_sum = sum(item[-1] for item in exit_list)
            prior_sum = current_sum + pct_exit
            if current_sum == 0:
                continue
            factor = prior_sum / current_sum
            for i in range(len(exit_list)):
                exit_list[i][-1] *= factor
            log_general.info(f'all remaining active {exit_type} exit percentages have been multiplied by a factor of {factor} to readjust for the previous confirmed exit')

    def _advise(self):
        self._update_trailing_exits_if_needed()
        for exit_type in self.exit_types:
            exit_list, exit_pct_sum = self._check_exits(exit_type, exit_list, exit_pct_sum)
            if exit_pct_sum >= 1:
                return exit_list
        return None

    def _update_trailing_exits_if_needed(self):
        if self.trailing_stop_loss or self.trailing_take_profit or self.true_trailing_take_profit:
            self._update_trailing_exits()

    def _check_exits(self, exit_type, exit_list, exit_pct_sum):
        exit_attr = getattr(self, exit_type)
        for idx, exit in enumerate(exit_attr):
            if self._is_exit_triggered(exit_type, exit):
                log_general.info(f'{exit_type} triggered for token_address: {self.token_address} at set_price: {exit[0]} current_price: {self.current_price}')
                exit_list.append((exit_type, exit[-1], idx))
            exit_pct_sum += exit[-1]
            if exit_pct_sum >= 1:
                return exit_list, exit_pct_sum
        return exit_list, exit_pct_sum

    def _is_exit_triggered(self, exit_type, exit):
        match exit_type:
            case 'stop_loss' | 'trailing_stop_loss' | 'trailing_take_profit':
                return self.current_price <= exit[0]
            case 'take_profit' | 'true_trailing_take_profit':
                return self.current_price >= exit[0]
            
    def _update_trailing_exits(self):
        if self.trailing_stop_loss and (self.current_price == self.highest_price):
            for idx, exit in enumerate(self.trailing_stop_loss):
                new_tsl = self.current_price - (self.current_price * exit[1])
                self.trailing_stop_loss[idx][0] = new_tsl
                log_general.info(f'trailing_stop_loss for token_address: {self.token_address} has been updated to exit_price = {new_tsl}, current_price = {self.current_price}')
        if self.trailing_take_profit:
            for idx, exit in enumerate(self.trailing_take_profit):
                if (exit[0] == None) and (self.current_price >= exit[2]):
                    new_ttp = self.current_price - (self.current_price * exit[1])
                    self.trailing_take_profit[0] = new_ttp 
                    log_general.info(f'trailing_take_profit for token_address: {self.token_address} has been triggered at current_price = {self.current_price}, exit_price = {new_ttp}')
                elif (exit[0] != None) and (self.current_price == self.highest_price):
                    new_ttp = self.current_price - (self.current_price * exit[1])
                    self.trailing_stop_loss[idx][0] = new_ttp
                    log_general.info(f'trailing_take_profit for token_address: {self.token_address} has been updated to exit_price = {new_ttp}, current_price = {self.current_price}')
        if self.true_trailing_take_profit


    def add_entry(self, txid, entry_price, position_size, unixtime):
        self.entries[txid] = (entry_price, position_size, unixtime)
        self._recalculate_position()

    def _recalculate_position(self):
        total_value = sum(price * size for price, size in self.entries.values())
        total_size = sum(size for _, size in self.entries.values())
        self.avg_price = total_value / total_size
        self.position_size = total_size - sum(size for _, size in self.exits.values())

    def remove_exit_condition(self, exit_type, idx):
        exit_list = getattr(self, exit_type)
        try:
            del exit_list[idx]
        except IndexError:
            log_general.warning(f"Invalid index; attempting to remove {exit_type} from {self.token_address} position; no action taken.")

    def get_exit_condition(self, exit_type, idx):
        exit_list = getattr(self, exit_type)
        try:
            return exit_list[idx]
        except IndexError:
            log_general.warning(f"Invalid index; attempting to remove {exit_type} from {self.token_address} position; no action taken.")

    def add_stop_loss(self, sl_pct=0.05, pct_exit=1):
        exit_price = self.current_price - self.current_price * sl_pct
        exit_condition = (exit_price, pct_exit)
        self.stop_loss.append(exit_condition)
        self.stop_loss.sort(key=lambda x: x[0], reverse=True)

    def add_take_profit(self, pct_exit=1, tp_pct=0.05):
        exit_price = self.current_price + self.current_price * tp_pct
        exit_condition = (exit_price, pct_exit)
        self.take_profit.append(exit_condition)
        self.take_profit.sort(key=lambda x: x[0], reverse=False)

    def add_trailing_stop_loss(self, pct_trail, pct_exit=1):
        exit_price = self.current_price - (self.current_price * pct_trail)
        exit_condition = (exit_price, pct_trail, pct_exit)
        self.trailing_stop_loss.append(exit_condition)
        self.trailing_stop_loss.sort(key=lambda x: x[1], reverse=False)

    def add_trailing_take_profit(self, profit_target_pct, pct_trail, pct_exit=1):
        trigger_price = self.current_price + (self.current_price * profit_target_pct)
        exit_price = None
        exit_condition = (exit_price, pct_trail, trigger_price, pct_exit)
        self.trailing_take_profit.append(exit_condition)
        self.trailing_take_profit.sort(key=lambda x: (x[0] is None, x[0]))

    def add_true_trailing_take_profit(self, pct_trail, pct_exit=1):
        exit_price = self.current_price + (self.current_price * pct_trail)
        exit_condition = (exit_price, pct_trail, pct_exit)
        self.true_trailing_take_profit.append(exit_condition)
        self.true_trailing_take_profit.sort(key=lambda x: x[1])

class PositionContainer:
    __slots__ = ['active_holdings', 'strategy_id']

    def __init__(self, strategy_id):
        self.active_holdings = OrderedDict()
        self.strategy_id = strategy_id

    def add_position(self, *args, **kwargs):
        token_address = args[0] if len(args) > 0 else kwargs.get('token_address')
        txid = args[1] if len(args) > 1 else kwargs.get('txid')
        entry_price = args[2] if len(args) > 2 else kwargs.get('entry_price')
        position_size = args[3] if len(args) > 3 else kwargs.get('position_size')
        unixtime = args[4] if len(args) > 4 else kwargs.get('unixtime')

        if None in [token_address, txid, entry_price, position_size, unixtime]:
            raise ValueError("All required position parameters must be provided.")

        self.active_holdings[token_address] = MarketPosition(txid, token_address, entry_price, position_size, unixtime)

class Stream:
    __slots__ = ['data']

    def __init__(self, data):
        self.data : np.array = self.arrange(data)

    def __iter__(self):
        return iter(self.data)
    
    def __getitem__(self, index):
        return self.data[index]

    def arrange(self, data):
        if isinstance(data, pd.Series):
            return data.values
        else:
            raise ValueError("Input must be a pandas Series")
        
    def mean(self, length=1, lag=0) -> float:
        if lag + length > len(self.data):
            length = len(self.data) - lag 
        segment = self.data[-1 - lag - length: -1 - lag if lag > 0 else None]
        return np.mean(segment)
    
    def max(self, length=1, lag=0) -> float:
        if lag + length > len(self.data):
            length = len(self.data) - lag
        segment = self.data[-1 - lag - length: -1 - lag if lag > 0 else None]
        return np.max(segment)

    def min(self, length=1, lag=0) -> float:
        if lag + length > len(self.data):
            length = len(self.data) - lag
        segment = self.data[-1 - lag - length: -1 - lag if lag > 0 else None]
        return np.min(segment)

    def std_dev(self, length=1, lag=0) -> float:
        if lag + length > len(self.data):
            length = len(self.data) - lag
        segment = self.data[-1 - lag - length: -1 - lag if lag > 0 else None]
        return np.std(segment)

    def covariance(self, other, length=1, lag=0) -> float:
        if isinstance(other, Stream):
            available_length = min(len(self.data) - lag, len(other.data) - lag)
            length = min(length, available_length)
            if length > 0:
                x = self.data[-1 - lag - length: -1 - lag if lag > 0 else None]
                y = other.data[-1 - lag - length: -1 - lag if lag > 0 else None]
                return np.cov(x, y)[0, 1]
        return 0

    def crossed_above(self, other, lag=0) -> bool:
        if isinstance(other, Stream):
            if lag < len(self.data) - 1 and lag < len(other.data) - 1:
                return self.data[-1 - lag] > other.data[-1 - lag] and self.data[-2 - lag] <= other.data[-2 - lag]
        elif isinstance(other, (int, float)):
            if lag < len(self.data) - 1:
                return self.data[-1 - lag] > other and self.data[-2 - lag] <= other
        return False

    def crossed_below(self, other, lag=0) -> bool:
        if isinstance(other, Stream):
            if lag < len(self.data) - 1 and lag < len(other.data) - 1:
                return self.data[-1 - lag] < other.data[-1 - lag] and self.data[-2 - lag] >= other.data[-2 - lag]
        elif isinstance(other, (int, float)):
            if lag < len(self.data) - 1:
                return self.data[-1 - lag] < other and self.data[-2 - lag] >= other
        return False
    
    def has_crossed_above(self, other, lookback=0) -> bool:
        for lag in range(lookback + 1):
            if self.crossed_above(other, lag):
                return True
        return False

    def has_crossed_below(self, other, lookback=0) -> bool:
        for lag in range(lookback + 1):
            if self.crossed_below(other, lag):
                return True
        return False
    
    def is_above(self, value, lag=0) -> bool:
        return self.data[-1 - lag] > value if lag < len(self.data) else False

    def is_below(self, value, lag=0) -> bool:
        return self.data[-1 - lag] < value if lag < len(self.data) else False

    def is_rising(self, length=1, lag=0) -> bool:
        return self.slope(lag, length) > 0

    def is_falling(self, length=1, lag=0) -> bool:
        return self.slope(lag, length) < 0
    
    def average_gain(self, length=1, lag=0):
        if lag + length > len(self.data):
            length = len(self.data) - lag
        segment = self.data[-1 - lag - length: -1 - lag if lag > 0 else None]
        changes = np.diff(segment)
        previous_values = segment[:-1]
        valid_indices = previous_values != 0 
        valid_changes = changes[valid_indices]
        valid_previous_values = previous_values[valid_indices]
        percentage_changes = valid_changes / valid_previous_values * 100
        gains = np.where(percentage_changes > 0, percentage_changes, 0)
        return np.mean(gains) if len(gains) > 0 else 0 

    def average_loss(self, length=1, lag=0):
        if lag + length > len(self.data):
            length = len(self.data) - lag
        segment = self.data[-1 - lag - length: -1 - lag if lag > 0 else None]
        changes = np.diff(segment)
        previous_values = segment[:-1]
        valid_indices = previous_values != 0 
        valid_changes = changes[valid_indices]
        valid_previous_values = previous_values[valid_indices]
        percentage_changes = valid_changes / valid_previous_values * 100
        losses = np.where(percentage_changes < 0, -percentage_changes, 0)
        return np.mean(losses) if len(losses) > 0 else 0 
    
    def slope(self, length=1, lag=0) -> float:
        if lag + length >= len(self.data):
            return None
        x = np.arange(length + 1).reshape(-1, 1)
        y = self.data[-1 - lag - length: -1 - lag if lag > 0 else None].reshape(-1, 1)
        model = LinearRegression()
        model.fit(x, y)
        return float(model.coef_[0][0]) if model else 0.0

    def predict(self, future_steps=1, length=1, lag=0) -> float | None:
        model = self._fit_model(lag, length)
        if model:
            highest_x = length 
            predicted_x = np.array([[highest_x + future_steps]])
            predicted_y = model.predict(predicted_x)
            return float(predicted_y[0][0])
        return None

    def _fit_model(self, length=1, lag=0):
        if lag + length >= len(self.data):
            return None
        x = np.arange(length + 1).reshape(-1, 1)
        y = self.data[-1 - lag - length: -1 - lag if lag > 0 else None].reshape(-1, 1)
        model = LinearRegression()
        model.fit(x, y)
        return model

class StreamContainer:
    __slots__ = ['unixtime', 'streams']
    
    def __init__(self, data, alias_list=None):
        if not isinstance(data, pd.DataFrame):
            raise ValueError("Data must be a pandas DataFrame")

        self.unixtime = data.index
        self.streams = {}

        if alias_list is None:
            alias_list = data.columns

        if len(alias_list) != len(data.columns):
            raise ValueError("Alias list must match the number of columns in the data")

        for alias, column in zip(alias_list, data.columns):
            self.streams[alias] = Stream(data[column])

    def __getattr__(self, name):
        if name in self.streams:
            return self.streams[name]
        else:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __getitem__(self, key):
        return self.streams[key]

    def __repr__(self):
        return f"<StreamContainer with streams: {list(self.streams.keys())}>"
