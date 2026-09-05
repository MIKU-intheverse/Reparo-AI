from abc import ABC, abstractmethod


class DataProvider(ABC):
    """
    Common interface the dashboard and the AI agent talk to. The dashboard
    never knows whether it's backed by RazorpayProvider (Live) or
    SimulationProvider (Test) — the environment router in
    app/providers/factory.py picks the implementation per authenticated
    request based on the user's account environment.
    """

    @abstractmethod
    def get_payments(self, limit: int = 20, skip: int = 0, status: str | None = None) -> dict: ...

    @abstractmethod
    def get_payment(self, payment_id: str) -> dict | None: ...

    @abstractmethod
    def get_orders(self, limit: int = 20, skip: int = 0) -> dict: ...

    @abstractmethod
    def get_order(self, order_id: str) -> dict | None: ...

    @abstractmethod
    def get_refunds(self, limit: int = 20, skip: int = 0) -> dict: ...

    @abstractmethod
    def get_customers(self, limit: int = 20, skip: int = 0) -> dict: ...

    @abstractmethod
    def get_analytics(self, days: int = 14) -> dict: ...

    @abstractmethod
    def get_settlements(self, limit: int = 20, skip: int = 0) -> dict: ...

    @abstractmethod
    def get_disputes(self, limit: int = 20, skip: int = 0) -> dict: ...

    @abstractmethod
    def search_transactions(self, query: str, limit: int = 20) -> dict: ...

    @abstractmethod
    def create_test_payment(self, **kwargs) -> dict:
        """Only meaningful for SimulationProvider; RazorpayProvider raises."""
        ...
