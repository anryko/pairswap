# Pairswap

## Example
```python
>>> from pairswap import ETHPair
>>>
>>> TEST_ADDRESS = '0x26fA8aac763B29AFBFEC7F23C85c1da57530781F'
>>> TEST_PRIVATE_KEY = '25954a23ff10562f3d7e34b55faaa920f04cd576380de04a52f187760db28e70'
>>> TEST_PROVIDER = 'wss://kovan.infura.io/ws/v3/ad54ae9fe2a694a99c62e8fb1fba244e'
>>> TEST_BONDLY = '0xde2005691855e2c71864828a531b47c4537659d4'
>>>
>>> pair = ETHPair(
...     address=TEST_ADDRESS,
...     private_key=TEST_PRIVATE_KEY,
...     provider=TEST_PROVIDER,
...     token=TEST_BONDLY,
... )
>>> pair.is_connected
True
>>> pair
<ETHPair(BONDLY)@0x7ff5f320da60>
>>> pair.balance
1.831966236171743
>>> pair.token_balance
119.63256903080517
>>> pair.weth_address
'0x5Ed806391C930321A89c29a1C0dCE237F30012f1'
>>> pair.price
348.0490514924989
>>> pair.token_price
0.001609960895976091
>>> pair.suggest_gas_price()
1800000000
>>> from web3 import Web3
>>> gas_price = Web3.toWei(1, 'gwei')
>>> pair.swap(0.05, gas=200000, gas_price=gas_price)
'0xbd7e8a9c7883ea8c72efa875d0e4466a705f798d81c7b4d2cbeab6461d24f8f4'
>>> pair.wait('0xbd7e8a9c7883ea8c72efa875d0e4466a705f798d81c7b4d2cbeab6461d24f8f4')
AttributeDict({'blockHash'...
>>> pair.balances
(1.781855709171742, 149.55144756540705)
>>> pair.wait(pair.unswap(50, gas=200000, gas_price=gas_price))
AttributeDict({'blockHash'...
>>> pair.balances
(1.862722511685864, 99.55144756540705)
```
