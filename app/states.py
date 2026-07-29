"""FSM-состояния."""

from aiogram.fsm.state import State, StatesGroup


class MainSG(StatesGroup):
    menu = State()


class SshSG(StatesGroup):
    menu = State()
    choose_key_type = State()
    get_passphrase = State()
    offer_export = State()
    get_target = State()
    confirm_host_key = State()
    wait_password = State()
    wait_2fa = State()
    get_existing_public_key = State()
    wait_key_to_validate = State()


class HashSG(StatesGroup):
    choose_algorithm = State()
    info = State()
    get_input = State()


class X509SG(StatesGroup):
    menu = State()
    common_name = State()
    organization = State()
    country = State()
    state_province = State()
    locality = State()
    email = State()
    choose_days = State()
    get_passphrase = State()
