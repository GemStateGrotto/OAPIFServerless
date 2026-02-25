"""Auth stack — Cognito User Pool, clients, groups, and domain.

This stack contains authentication infrastructure: a Cognito User Pool
with OIDC configuration, app clients for interactive login (PKCE) and
machine-to-machine (client credentials), and group definitions matching
the access control model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aws_cdk as cdk
from aws_cdk import (
    aws_certificatemanager as acm,
)
from aws_cdk import (
    aws_cognito as cognito,
)
from constructs import Construct

if TYPE_CHECKING:
    from deploy.config import DeploymentConfig


class AuthStack(cdk.Stack):
    """Cognito User Pool and related auth resources for OAPIF."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: DeploymentConfig,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Cognito User Pool ---
        self.user_pool = cognito.UserPool(
            self,
            "OapifUserPool",
            user_pool_name=f"{config.stack_prefix}-{config.environment}-users",
            self_sign_up_enabled=False,  # Admin-only user creation
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=(cdk.RemovalPolicy.DESTROY if config.environment == "dev" else cdk.RemovalPolicy.RETAIN),
        )

        # --- Hosted UI Domain ---
        # The domain prefix must be globally unique across all AWS accounts.
        self.user_pool_domain = self.user_pool.add_domain(
            "OapifDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"{config.cognito_domain_prefix}-{config.environment}",
            ),
        )

        # --- Custom Cognito Domain (optional) ---
        self.custom_user_pool_domain: cognito.UserPoolDomain | None = None
        if config.cognito_custom_domain_name and config.cognito_custom_domain_certificate_arn:
            self.custom_user_pool_domain = self.user_pool.add_domain(
                "OapifCustomDomain",
                custom_domain=cognito.CustomDomainOptions(
                    domain_name=config.cognito_custom_domain_name,
                    certificate=acm.Certificate.from_certificate_arn(
                        self,
                        "CognitoCustomDomainCert",
                        config.cognito_custom_domain_certificate_arn,
                    ),
                ),
            )

        # --- Google OAuth Federation (optional) ---
        self.google_provider: cognito.UserPoolIdentityProviderGoogle | None = None
        supported_providers: list[cognito.UserPoolClientIdentityProvider] = [
            cognito.UserPoolClientIdentityProvider.COGNITO,
        ]

        if config.google_oauth_client_id and config.google_oauth_client_secret:
            self.google_provider = cognito.UserPoolIdentityProviderGoogle(
                self,
                "Google",
                user_pool=self.user_pool,
                client_id=config.google_oauth_client_id,
                client_secret_value=cdk.SecretValue.unsafe_plain_text(
                    config.google_oauth_client_secret,
                ),
                scopes=["openid", "email", "profile"],
                attribute_mapping=cognito.AttributeMapping(
                    email=cognito.ProviderAttribute.GOOGLE_EMAIL,
                    fullname=cognito.ProviderAttribute.GOOGLE_NAME,
                ),
            )
            supported_providers.append(
                cognito.UserPoolClientIdentityProvider.GOOGLE,
            )

        # --- App Client: Interactive Login (Authorization Code + PKCE) ---
        self.app_client = self.user_pool.add_client(
            "AppClient",
            user_pool_client_name=f"{config.stack_prefix}-{config.environment}-app",
            generate_secret=False,  # Public client (PKCE)
            auth_flows=cognito.AuthFlow(
                user_srp=True,
                admin_user_password=True,  # Required for acceptance test auth
            ),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True,
                ),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.PROFILE,
                    cognito.OAuthScope.EMAIL,
                ],
                callback_urls=["http://localhost:8765/callback"],
                logout_urls=["http://localhost:8765/logout"],
            ),
            supported_identity_providers=supported_providers,
            access_token_validity=cdk.Duration.hours(1),
            id_token_validity=cdk.Duration.hours(1),
            refresh_token_validity=cdk.Duration.days(365),
            prevent_user_existence_errors=True,
        )

        # Ensure the app client is created after the Google provider
        if self.google_provider:
            self.app_client.node.add_dependency(self.google_provider)

        # --- App Client: Machine-to-Machine (Client Credentials) ---
        # Requires a resource server for scoped access.
        self.resource_server = self.user_pool.add_resource_server(
            "OapifResourceServer",
            identifier=f"{config.stack_prefix}-{config.environment}-api",
            scopes=[
                cognito.ResourceServerScope(
                    scope_name="features.read",
                    scope_description="Read features",
                ),
                cognito.ResourceServerScope(
                    scope_name="features.write",
                    scope_description="Create, update, and delete features",
                ),
            ],
        )

        self.m2m_client = self.user_pool.add_client(
            "M2MClient",
            user_pool_client_name=f"{config.stack_prefix}-{config.environment}-m2m",
            generate_secret=True,  # Confidential client
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    client_credentials=True,
                ),
                scopes=[
                    cognito.OAuthScope.custom(f"{config.stack_prefix}-{config.environment}-api/features.read"),
                    cognito.OAuthScope.custom(f"{config.stack_prefix}-{config.environment}-api/features.write"),
                ],
            ),
            supported_identity_providers=[
                cognito.UserPoolClientIdentityProvider.COGNITO,
            ],
            access_token_validity=cdk.Duration.hours(1),
            prevent_user_existence_errors=True,
        )
        # M2M client depends on the resource server existing first
        self.m2m_client.node.add_dependency(self.resource_server)

        # --- Cognito Groups ---
        # Organization groups (one per org, e.g. "org:TestOrgA")
        # Visibility-level groups within each org
        # Role groups (editor, admin, viewer)
        #
        # Groups are created dynamically per-organization at deploy time
        # or via admin API. Here we define the role groups that apply
        # across all organizations.

        role_groups = ["admin", "editor", "viewer"]
        for role in role_groups:
            cognito.CfnUserPoolGroup(
                self,
                f"RoleGroup-{role}",
                group_name=role,
                user_pool_id=self.user_pool.user_pool_id,
                description=f"Global {role} role",
            )

        # Example org group — in production these would be created via
        # admin API or a custom resource. We create one for dev/testing.
        if config.environment == "dev":
            cognito.CfnUserPoolGroup(
                self,
                "OrgGroup-TestOrgA",
                group_name="org:TestOrgA",
                user_pool_id=self.user_pool.user_pool_id,
                description="Organization: TestOrgA",
            )
            for level in ["members", "restricted"]:
                cognito.CfnUserPoolGroup(
                    self,
                    f"VisibilityGroup-TestOrgA-{level}",
                    group_name=f"TestOrgA:{level}",
                    user_pool_id=self.user_pool.user_pool_id,
                    description=f"TestOrgA {level} visibility access",
                )

        # --- Outputs ---
        cdk.CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolArn", value=self.user_pool.user_pool_arn)
        cdk.CfnOutput(
            self,
            "UserPoolDomainUrl",
            value=self.user_pool_domain.base_url(),
        )
        if self.custom_user_pool_domain:
            cdk.CfnOutput(
                self,
                "CognitoCustomDomainCloudFrontAlias",
                value=self.custom_user_pool_domain.cloud_front_endpoint,
                description="CNAME target for the Cognito custom domain",
            )
        cdk.CfnOutput(
            self,
            "AppClientId",
            value=self.app_client.user_pool_client_id,
        )
        cdk.CfnOutput(
            self,
            "M2MClientId",
            value=self.m2m_client.user_pool_client_id,
        )
