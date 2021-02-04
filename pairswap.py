import os
import json
import logging
import time

from datetime import datetime

from typing import (
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
)

from web3 import Web3
from web3.gas_strategies.time_based import (
    fast_gas_price_strategy,
    medium_gas_price_strategy,
    slow_gas_price_strategy,
    glacial_gas_price_strategy,
)
from web3.types import (
    TxReceipt,
    TxParams,
)


Wei = int
Ether = float
TokWei = int
Token = float
TxHash = str

log = logging.getLogger('pairswap')


class Utils:
    @staticmethod
    def load_abi(file_name: str) -> str:
        file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'assets',
            file_name
        )
        with open(file_path) as f:
            return json.load(f)['abi']


GAS_STRATEGY_MAP: Dict[str, Callable] = {
    'fast': fast_gas_price_strategy,  # 1 minute
    'medium': medium_gas_price_strategy,  # 5 minutes
    'slow': slow_gas_price_strategy,  # 1 hour
    'glacial': glacial_gas_price_strategy,  # 24 hours
}

MAX_APPROVAL_HEX: str = '0x' + 'f' * 64
MAX_APPROVAL_INT: int = int(MAX_APPROVAL_HEX, 16)

FACTORY_ADDRESS: str = '0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f'
FACTORY_ABI: str = Utils.load_abi('IUniswapV2Factory.json')

ROUTER_ADDRESS: str = '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D'
ROUTER_ABI: str = Utils.load_abi('IUniswapV2Router02.json')

ERC20_ABI: str = Utils.load_abi('IUniswapV2ERC20.json')
PAIR_ABI: str = Utils.load_abi('IUniswapV2Pair.json')


class PairswapError(Exception):
    pass


class PairswapClient:
    def __init__(
        self,
        address: str,
        private_key: str,
        provider: str,
        gas: int,
        gas_price: Wei,
    ) -> None:
        self.address = Web3.toChecksumAddress(address)
        self.private_key = private_key
        self.provider = provider

        if self.provider.startswith('https://'):
            web3_provider = Web3.HTTPProvider(self.provider, request_kwargs={"timeout": 60})
        elif self.provider.startswith('wss://'):
            web3_provider = Web3.WebsocketProvider(self.provider)
        elif self.provider.startswith('/'):
            web3_provider = Web3.IPCProvider(self.provider)
        else:
            raise PairswapError(f"Unknown provider type '{self.provider}'")

        self.conn = Web3(web3_provider)
        if not self.is_connected:
            raise PairswapError(f"Connection failed to provider '{self.provider}'")

        self.tx_gas = gas
        self.tx_gas_price = gas_price

    @property
    def is_connected(self) -> bool:
        return self.conn.isConnected()

    def suggest_gas_price(self, mode: str = 'medium') -> Wei:
        """
        Suggests gas price depending on required transaction priority.
        Supported priorities are: 'fast', 'medium', 'slow', 'glacial'.

        Warning: This operation is very slow (~30sec)!
        """

        if mode not in GAS_STRATEGY_MAP:
            raise PairswapError(
                f"Unsupported gas strategy type, pick from: {[k for k in GAS_STRATEGY_MAP]}"
            )

        self.conn.eth.setGasPriceStrategy(GAS_STRATEGY_MAP[mode])
        return self.conn.eth.generateGasPrice()

    def __repr__(self) -> str:
        return f"<PairswapClient({self.provider})@{hex(id(self))}>"

    def _get_tx_params(
        self,
        amount: Wei = 0,
        gas: Optional[int] = None,
        gas_price: Optional[Wei] = None,
        nonce: Optional[int] = None,
    ) -> TxParams:
        return {
            'from': self.address,
            'value': amount,
            'gas': gas if gas is not None else self.tx_gas,
            'gasPrice': gas_price if gas_price is not None else self.tx_gas_price,
            'nonce': (
                nonce
                if nonce is not None
                else self.conn.eth.getTransactionCount(self.address)
            ),
        }

    def _submit_tx(self, func: Callable, params: Dict) -> TxHash:
        tx = func.buildTransaction(params)
        tx_signed = self.conn.eth.account.sign_transaction(tx, private_key=self.private_key)
        tx_hash = self.conn.eth.sendRawTransaction(tx_signed.rawTransaction)
        return Web3.toHex(tx_hash)


class ETHPair(PairswapClient):
    def __init__(
        self,
        address: str,
        private_key: str,
        provider: str,
        token: str,  # Token address
        max_slippage: float = 0.2,  # Fraction
        gas: int = Web3.toWei(100, 'gwei'),
        gas_price: Wei = 250000,
        transaction_timeout: int = 300,  # Seconds
    ) -> None:
        super().__init__(
            address,
            private_key,
            provider,
            gas,
            gas_price,
        )

        self.token = Web3.toChecksumAddress(token)
        self.max_slippage = max_slippage
        self.tx_timeout = transaction_timeout

        self.contract = self.conn.eth.contract(
            address=Web3.toChecksumAddress(FACTORY_ADDRESS),
            abi=FACTORY_ABI
        )
        self.router = self.conn.eth.contract(
            address=Web3.toChecksumAddress(ROUTER_ADDRESS),
            abi=ROUTER_ABI
        )
        self.token_contract = self.conn.eth.contract(
            address=Web3.toChecksumAddress(self.token),
            abi=PAIR_ABI
        )
        self.token_symbol = self.token_contract.functions.symbol().call()
        self.token_decimals = self.token_contract.functions.decimals().call()

    @staticmethod
    def _eth_to_wei(amount: Ether) -> Wei:
        return Wei(Web3.toWei(amount, 'ether'))

    @staticmethod
    def _wei_to_eth(amount: Wei) -> Ether:
        return Ether(Web3.fromWei(amount, 'ether'))

    def _token_to_tokwei(self, amount: Token) -> TokWei:
        return TokWei(amount * (10**self.token_decimals))

    def _tokwei_to_token(self, amount: TokWei) -> Token:
        return Token(amount / (10**self.token_decimals))

    @property
    def weth_address(self) -> str:
        return self.router.functions.WETH().call()

    @property
    def balance(self) -> Ether:
        """ Pair ETH balance.
        """
        balance: Wei = self.conn.eth.getBalance(self.address)
        return self._wei_to_eth(balance)

    @property
    def token_balance(self) -> Token:
        """ Pair token balance.
        """
        balance: TokWei = self.token_contract.functions.balanceOf(self.address).call()
        return self._tokwei_to_token(balance)

    @property
    def balances(self) -> Tuple[Ether, Token]:
        """ Current pair balance (ETH, Token)
        """
        return (self.balance, self.token_balance)

    def __repr__(self) -> str:
        return f"<ETHPair({self.token_symbol})@{hex(id(self))}>"

    def __str__(self) -> str:
        return json.dumps({'ETH': self.balance, self.token_symbol: self.token_balance})

    def __bool__(self) -> bool:
        return (
            self.is_connected
            and (
                bool(self.balance)
                or bool(self.token_balance)
            )
        )

    @property
    def _tx_deadline(self) -> int:
        """ Generate a deadline timestamp for transaction.
        """
        return int(time.time()) + self.tx_timeout

    def _tokwei_price_in_wei(self, amount: TokWei) -> Wei:
        """ Amount of tokens you can expect to get for supplied amount of Wei.
        """
        return self.router.functions.getAmountsIn(
            amount,
            [self.weth_address, self.token]
        ).call()[0]

    def _wei_price_in_tokwei(self, amount: Wei) -> TokWei:
        """ Amount of Wei you can expect to get for supplied amount of tokens.
        """
        return self.router.functions.getAmountsOut(
            amount,
            [self.weth_address, self.token]
        ).call()[-1]

    @property
    def price(self, amount: Ether = 1) -> Token:
        """ Price of ETH in Token.
        """
        return self._tokwei_to_token(
            self._wei_price_in_tokwei(
                self._eth_to_wei(amount)
            )
        )

    @property
    def token_price(self, amount: Token = 1) -> Ether:
        """ Price of Token in ETH.
        """
        return self._wei_to_eth(
            self._tokwei_price_in_wei(
                self._token_to_tokwei(amount)
            )
        )

    def is_token_approved(
        self,
        amount: TokWei = MAX_APPROVAL_INT,
    ) -> bool:
        erc20_contract = self.conn.eth.contract(
            address=self.token,
            abi=PAIR_ABI
        )

        approved_amount = erc20_contract.functions.allowance(
            self.address, self.router.address
        ).call()

        return approved_amount >= amount

    def wait(self, hash: TxHash, timeout: int = 3600) -> TxReceipt:
        return self.conn.eth.waitForTransactionReceipt(hash, timeout=timeout)

    def approve_token(
        self,
        max_approval: TokWei = MAX_APPROVAL_INT,
        gas: Optional[int] = None,
        gas_price: Optional[Wei] = None,
        nonce: Optional[int] = None,
    ) -> None:
        if self.is_token_approved(max_approval):
            log.debug(
                (
                    f"The {self._tokwei_to_token(max_approval)} of "
                    f"{self.token_symbol} is already approved for transfer"
                )
            )
            return

        log.info(
            (
                f"Approving {self._tokwei_to_token(max_approval)} "
                f"of {self.token_symbol} for transfer"
            )
        )
        log.debug(f"Approval gas: {gas or self.tx_gas}")
        log.debug(f"Approval gas price: {gas_price or self.tx_gas_price} Wei")
        log.debug(f"Approval nonce: {nonce or 'Default'}")

        erc20_contract = self.conn.eth.contract(
            address=self.token,
            abi=ERC20_ABI
        )

        func = erc20_contract.functions.approve(self.router.address, max_approval)
        params = self._get_tx_params(
            gas=gas,
            gas_price=gas_price,
            nonce=nonce,
        )

        # NOTE: Wallet nonce update is lagging behind and is not updated immediately after
        # transaction receipt is received. This causes same nonce to be reused on the next
        # transaction following approval.
        current_nonce = (
            nonce
            if nonce is not None
            else self.conn.eth.getTransactionCount(self.address)
        )
        tx_hash = self._submit_tx(func, params)

        timeout = 3600  # 1 hour
        timer_start = time.monotonic()
        self.wait(tx_hash, timeout)

        # NOTE: Wait for nonce to be incremented of for the timeout interval to run out.
        while (
            current_nonce == self.conn.eth.getTransactionCount(self.address)
            and time.monotonic() - timer_start <= timeout
        ):
            time.sleep(0.5)

        log.info(
            (
                f"The {self._tokwei_to_token(max_approval)} of "
                f"{self.token_symbol} was approved for transfer"
            )
        )

    def swap(
        self,
        amount: Ether,
        gas: Optional[int] = None,
        gas_price: Optional[Wei] = None,
        nonce: Optional[int] = None,
    ) -> TxHash:
        """ Swap ETH to Token.
        """
        swap_amount: Wei = self._eth_to_wei(amount)

        amount_out_min: TokWei = TokWei(
            (1 - self.max_slippage) * self._wei_price_in_tokwei(swap_amount)
        )
        path = [self.weth_address, self.token]
        to_address = self.address
        deadline = self._tx_deadline

        log.info(
            (
                f"Swapping {amount} ETH for a minimum of "
                f"{self._tokwei_to_token(amount_out_min)} {self.token_symbol}"
            )
        )
        log.debug(f"Swap path: {path}")
        log.debug(f"Swap address: {to_address}")
        log.debug(f"Swap deadline: {datetime.fromtimestamp(deadline)}")
        log.debug(f"Swap gas: {gas or self.tx_gas_price}")
        log.debug(f"Swap gas price: {gas_price or self.tx_gas} Wei")
        log.debug(f"Swap nonce: {nonce or 'Default'}")

        func = self.router.functions.swapExactETHForTokens(
            amount_out_min,
            path,
            to_address,
            deadline,
        )
        params = self._get_tx_params(
            amount=swap_amount,
            gas=gas,
            gas_price=gas_price,
            nonce=nonce,
        )

        return self._submit_tx(func, params)

    def unswap(
        self,
        amount: Token,
        gas: Optional[int] = None,
        gas_price: Optional[Wei] = None,
        nonce: Optional[int] = None,
    ) -> TxHash:
        """ Swap Token to ETH.
        """
        unswap_amount: TokWei = self._token_to_tokwei(amount)

        self.approve_token(
            max_approval=unswap_amount,
            gas=gas,
            gas_price=gas_price,
            nonce=nonce,
        )

        amount_out_min: Wei = Wei(
            (1 - self.max_slippage) * self._tokwei_price_in_wei(unswap_amount)
        )
        path = [self.token, self.weth_address]
        to_address = self.address
        deadline = self._tx_deadline

        log.info(
            (
                f"Unswapping {amount} {self.token_symbol} for a minimum of "
                f"{self._wei_to_eth(amount_out_min)} ETH"
            )
        )
        log.debug(f"Unswap path: {path}")
        log.debug(f"Unswap address: {to_address}")
        log.debug(f"Unswap deadline: {datetime.fromtimestamp(deadline)}")
        log.debug(f"Unswap gas: {gas or self.tx_gas}")
        log.debug(f"Unswap gas price: {gas_price or self.tx_gas_price} Wei")
        log.debug(f"Unswap nonce: {nonce or 'Default'}")

        func = self.router.functions.swapExactTokensForETH(
            unswap_amount,
            amount_out_min,
            path,
            to_address,
            deadline,
        )
        params = self._get_tx_params(
            gas=gas,
            gas_price=gas_price,
            nonce=nonce,
        )

        return self._submit_tx(func, params)
