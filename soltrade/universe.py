import requests
import json
import time
import aiosqlite
import aiohttp
from log import log_general
from config import config
from pooling import DatabaseConnectionPool
from utils import *

class Universe:
    def __init__(self, configs, db_pool):
        self.universe_id = configs.get('universe_id')
        self.platform = configs.get('platform')
        self.token_list_sort_by = configs.get('token_list_sort_by')
        self.token_list_sort_type = configs.get('token_list_sort_type')
        self.page_limit = configs.get('token_list_page_limit')
        self.intervals = configs.get('intervals')
        self.tradeable_assets_update_minutes = configs.get('tradeable_assets_update_minutes')
        self.ohclv_update_minutes = configs.get('ohclv_update_minutes')
        self.api_token_fetch_limit = configs.get('api_token_fetch_limit')
        self.market_cap_bins = configs.get('market_cap_bins')
        self.min_hours_since_creation = configs.get('min_hours_since_creation')
        self.max_top_10_holders_pct = configs.get('max_top_10_holders_pct')
        self.min_liquidity = configs.get('min_liquidity')
        self.min_volume_pct_market_cap_quintile = configs.get('min_volume_pct_market_cap_quintile')
        self.min_volume_change_pct_quintile = configs.get('min_volume_change_pct_quintile')
        self.db_pool = db_pool
        self.headers = {
            "x-chain": self.platform,
            "X-API-KEY": config().get('birdeye_api_key')
        }
        self.session = None

    @classmethod
    async def create(cls, configs, db_pool):
        instance = cls(configs, db_pool)
        assert instance.universe_id is not None and isinstance(instance.universe_id, str), "universe_id must be a non-empty string"
        assert instance.platform is not None and isinstance(instance.platform, str), "platform must be a non-empty string"
        assert instance.intervals is not None and isinstance(instance.platform, list), "intervals must be a non-empty list"
        assert instance.db_pool is not None and isinstance(instance.db_pool, DatabaseConnectionPool), "db_pool must be a DatabaseConnectionPool object"
        await instance.init_db_column()
        return instance

    async def open_aiohttp_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def close_aiohttp_session(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def init_db_column(self):
        query = "PRAGMA table_info(tradeable_assets)"
        columns_info = await self.db_pool.read(query)
        columns = [info[1] for info in columns_info]
        
        if self.universe_id not in columns:
            alter_query = f"ALTER TABLE tradeable_assets ADD COLUMN {self.universe_id} BOOLEAN DEFAULT FALSE"
            await self.db_pool.write(alter_query)
            
    async def set_currently_tradeable_to_false(self):
        update_query = f"UPDATE tradeable_assets SET {self.universe_id} = FALSE"
        await self.db_pool.write(update_query)

    async def set_currently_tradeable_to_true(self, token_address):
        update_query = f"UPDATE tradeable_assets SET {self.universe_id} = TRUE WHERE token_address = ?"
        params = (token_address,)
        await self.db_pool.write(update_query, params)

    @handle_rate_limiting_aiohttp()
    async def fetch_token_security_info(self, token_address):
        url = f"https://public-api.birdeye.so/defi/token_security?address={token_address}"
        async with self.session.get(url, headers=self.headers) as response:
            return response
    
    @handle_rate_limiting_aiohttp()
    async def fetch_token_list_page(self, offset):
        url = f"https://public-api.birdeye.so/public/tokenlist?sort_by={self.token_list_sort_by}&sort_type={self.token_list_sort_type}&offset={offset}&limit={self.page_limit}"
        async with self.session.get(url, headers=self.headers) as response:
            return response
    
    @handle_rate_limiting_aiohttp()
    async def fetch_new_ohlcv_data(self, token_address, interval, unix_time_start, unix_time_end):
        url = f"https://public-api.birdeye.so/defi/ohlcv?address={token_address}&type={interval}&time_from={unix_time_start}&time_to={unix_time_end}"
        async with self.session.get(url, headers=self.headers) as response:
            return response
    
    async def get_all_currently_tradeable_assets(self):
        query = f"SELECT token_address FROM tradeable_assets WHERE {self.universe_id} = TRUE"
        rows = await self.db_pool.read(query)
        return [row[0] for row in rows]

    async def token_exists_in_database(self, token_address):
        query = "SELECT 1 FROM tradeable_assets WHERE token_address = ?"
        params = (token_address,)
        result = await self.db_pool.read(query, params)
        return bool(result) 
    
    async def last_ohclv_update_unixtime(self, token_address, interval):
        query = "SELECT unixtime FROM tradeable_asset_prices WHERE token_address = ? AND interval = ? ORDER BY unixtime DESC LIMIT 1"
        params = (token_address, interval)
        result = await self.db_pool.read(query, params)
        return result[0][0] if result else None

    async def get_token_creation_unixtime(self, token_address):
        query = "SELECT creation_unixtime FROM tradeable_assets WHERE token_address = ?"
        params = (token_address,)
        result = await self.db_pool.read(query, params)
        return result[0][0] if result else None

    async def insert_into_tradeable_assets_info(self, entry):
        now = int(time.time())
        sql = '''INSERT INTO tradeable_asset_info (unixtime, token_address, top_10_holders_pct, volume, 
                volume_change_pct, market_cap, liquidity, volume_pct_market_cap)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)'''
        params = (now, entry['token_address'], entry['top_10_holders_pct'], entry['volume'], 
                entry['volume_change_pct'], entry['market_cap'], entry['liquidity'], entry['volume_pct_market_cap'])
        await self.db_pool.write(sql, params)
        log_general.info(f"token_address: {entry.get('token_address')} information updated in tradeable_assets_info for universe_id: {self.universe_id}")
    
    async def insert_into_tradaeble_assets(self, entry):
        sql = '''INSERT INTO tradeable_assets (token_address, name, symbol, platform, creation_unixtime, ?)
                VALUES (?, ?, ?, ?, ?, ?)'''
        params = (self.universe_id, entry['token_address'], entry['name'], entry['symbol'], self.platform, entry['creation_time'], True)
        await self.db_pool.write(sql, params)
        log_general.info(f"token_address: {entry.get('token_address')} added to tradeable_assets and set true for universe_id: {self.universe_id}")

    async def insert_into_tradeable_asset_prices(self, token_address, entries, interval):
        sql = '''INSERT INTO tradeable_asset_prices (token_address, unixtime, open, high, low, close, volume, interval)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)'''
        for data_point in entries:
            params = (token_address, data_point["unixTime"], data_point["o"], data_point["h"], data_point["l"], data_point["c"], data_point["v"], interval)
            await self.db_pool.write(sql, params)
        log_general.info(f"{len(entries)} OHCLV data points added to tradeable_asset_prices for token_address: {token_address} interval: {interval}")

    async def fill_entry(self, coin):
        volume = convert_or_default(coin.get('v24hUSD'), float, 0)
        volume_change_pct = convert_or_default(coin.get('v24hChangePercent'), float, 0)
        market_cap = convert_or_default(coin.get('mc'), float, 0)
        liquidity = convert_or_default(coin.get("liquidity"), float, 0)
        name = convert_or_default(coin.get('name'), str, '_')
        token_address = convert_or_default(coin.get('address'), str, '_')
        symbol = convert_or_default(coin.get('symbol'), str, '_')

        security_info = await self.fetch_token_security_info(token_address) 
        top10holderspct = convert_or_default(security_info['data'].get('top_10_holders_pct'), float, 0)
        creation_time = convert_or_default(security_info['data'].get('creationTime'), int, 0)

        entry = {
            'token_address': token_address, 'symbol': symbol, 'name': name, 'volume': volume,
            'volume_change_pct': volume_change_pct, 'market_cap': market_cap,
            'liquidity': liquidity, 'volume_pct_market_cap': volume / market_cap if market_cap else 0,
            'top_10_holders_pct': top10holderspct, 'creation_time': creation_time
        }

        preliminaries = all([
            volume, market_cap, liquidity, name != '_', token_address != '_', symbol != '_', 'Wormhole' not in name
        ])

        return entry, preliminaries

    @handle_aiohttp_session()
    async def fetch_coins_by_market_cap(self):
        universe = {n: [] for n in range(1, len(self.market_cap_bins) + 1)}
        min_mc, max_mc = self.market_cap_bins[0][0], self.market_cap_bins[-1][1]
        offset = 0
        while offset <= self.api_token_fetch_limit:
            coins = await self.fetch_token_list_page(offset)
            if not coins:
                break
            for coin in coins['data']['tokens']:
                entry, preliminaries = await self.fill_entry(coin)
                market_cap = entry.get('market_cap')
                if await self.token_exists_in_database(entry.get('token_address')):
                    await self.insert_into_tradeable_assets_info(entry)
                if (min_mc < market_cap <= max_mc) and preliminaries:
                    for idx, (lower_bound, upper_bound) in enumerate(self.market_cap_bins, start=1):
                        if lower_bound <= market_cap < upper_bound:
                            universe[idx].append(entry)
                            break
            offset += 50
        log_general.info(f"Queried {self.api_token_fetch_limit + 50} tokens from birdeye with sort_by: {self.token_list_sort_by} and sort_type: {self.token_list_sort_type} for universe_id: {self.universe_id}")
        return universe

    def filter_universe_by_age_and_security(self, universe):
        min_creation_time = int(time.time()) - (self.min_hours_since_creation * 3600)
        filtered_universe = {n: [] for n in range(1, len(self.market_cap_bins) + 1)}
        
        total_initial_count = sum(len(universe[key]) for key in universe)
        total_filtered_count = 0
        
        for key in universe:
            filtered_universe[key] = [
                asset for asset in universe[key]
                if asset['top_10_holders_pct'] <= self.max_top_10_holders_pct 
                and asset['creation_time'] <= min_creation_time
            ]
            total_filtered_count += len(filtered_universe[key])
        
        total_filtered_out_percentage = round((1 - float(total_filtered_count / total_initial_count)) * 100, 2)
        log_general.info(f"{total_filtered_out_percentage}% of initial universe filtered out by age and security for universe_id: {self.universe_id}")
        
        return filtered_universe
    
    def filter_universe_by_volume_and_liquidity(self, universe):
        def calculate_quintile_indices(length):
            return [int(length * i / 5) for i in range(len(self.market_cap_bins)+1)]

        def filter_by_quintile(data, key, min_quintile):
            if len(data) == 0:
                return []
            if 0 < len(data) < 5:
                return [max(data, key=lambda x: x[key])]

            sorted_data = sorted(data, key=lambda x: x[key])
            indices = calculate_quintile_indices(len(sorted_data))
            quintile_cutoff_index = indices[min_quintile - 1]
            return sorted_data[quintile_cutoff_index:]


        total_initial_count = sum(len(coins) for _, coins in universe.items())
        filtered_universe = []

        for _, coins in universe.items():
            liquidity_filtered_coins = [coin for coin in coins if coin['liquidity'] >= self.min_liquidity]
            volume_market_cap_filtered = filter_by_quintile(liquidity_filtered_coins, 'volume_pct_market_cap', self.min_volume_pct_market_cap_quintile)
            final_filtered = filter_by_quintile(volume_market_cap_filtered, 'volume_change_pct', self.min_volume_change_pct_quintile)
            filtered_universe.extend(final_filtered)

        total_filtered_count = len(filtered_universe)
        total_filtered_out_percentage = round((1 - float(total_filtered_count / total_initial_count)) * 100, 2)

        log_general.info(f"{total_filtered_out_percentage}% of initial universe further filtered out by volume and liquidity for universe_id: {self.universe_id}")
        return filtered_universe

    async def update_tradeable_assets(self):
        log_general.info(f"Beginning universe selection process for universe_id: {self.universe_id}")
        universe = await self.fetch_coins_by_market_cap()
        security_filtered_universe = self.filter_universe_by_age_and_security(universe)
        final_filtered_universe = self.filter_universe_by_volume_and_liquidity(security_filtered_universe)
        log_general.info(format_universe_composition(self.market_cap_bins, final_filtered_universe))
        await self.set_currently_tradeable_to_false()

        for asset in final_filtered_universe:
            token_address = asset['token_address']
            if await self.token_exists_in_database(token_address):
                await self.set_currently_tradeable_to_true(token_address)
            else:
                await self.insert_into_tradaeble_assets(asset)
                await self.insert_into_tradeable_assets_info(asset)

    @handle_aiohttp_session()
    async def update_tradeable_asset_prices(self, interval):
        token_addresses = await self.get_all_currently_tradeable_assets()

        for token_address in token_addresses:
            unix_time_end = int(time.time())
            result = await self.last_ohclv_update_unixtime(self, token_address, interval)
            if result:
                last_update_unix = result[0]
            else:
                creation_unixtime_result = await self.get_token_creation_unixtime(token_address)
                creation_unixtime = creation_unixtime_result[0] if creation_unixtime_result else unix_time_end
                if unix_time_end - creation_unixtime < interval_to_seconds('1W'):
                    last_update_unix = creation_unixtime
                else:
                    last_update_unix = unix_time_end - interval_to_seconds('1W')

            interval_seconds = interval_to_seconds(interval)
            if unix_time_end - last_update_unix >= interval_seconds:
                new_ohlcv_data = await self.fetch_new_ohlcv_data(token_address, interval, last_update_unix, unix_time_end)["data"]["items"]
                if new_ohlcv_data:
                    await self.insert_into_tradeable_asset_prices(token_address, new_ohlcv_data, interval)