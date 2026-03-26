# Contributing

To make contributions to this charm, you'll need a working
[development setup](https://documentation.ubuntu.com/juju/3.6/howto/manage-your-deployment/#set-up-your-deployment-local-testing-and-development).

You can create an environment for development with `tox`:

```shell
tox devenv -e integration
source venv/bin/activate
```

## Testing

This project uses `tox` for managing test environments. The following environments are available:

```shell
tox run -e format        # update your code according to linting rules
tox run -e lint          # code style and static type checking
tox run -e unit          # unit tests
tox run -e integration   # integration tests
tox                      # runs 'format', 'lint', and 'unit' environments
```

Integration tests require a Juju controller with a Kubernetes cloud and use the
[Jubilant](https://documentation.ubuntu.com/jubilant/) library. You can point the tests at a
pre-built charm file by setting the `CHARM_PATH` environment variable; otherwise the tests
look for a `.charm` file in the project directory.

## Build the charm

Build the charm in this git repository using:

```shell
charmcraft pack
```

## License

By contributing to this project, you agree that your contributions are licensed under the GNU Affero General Public License v3.0 only. See [LICENSE](LICENSE).
