import secrets


class SecurityConfig:

    PASSWORD_MIN_LENGTH = 8

    SESSION_TIMEOUT = 3600

    TOKEN_LENGTH = 64

    PASSWORD_SALT_LENGTH = 32

    SECRET_GENERATOR = secrets.token_hex