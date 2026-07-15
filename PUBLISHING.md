# Publishing ha-dawnloc

Create the repository as `slammo84/ha-dawnloc`, commit the project and push the
`main` branch.

The Home Assistant repository metadata and app URL are already configured for:

```text
https://github.com/slammo84/ha-dawnloc
```

For a release, update the version in `dawnloc/config.yaml` and
`dawnloc/app/__init__.py`, then create the tag:

```bash
git tag -a v0.1.0-rc.1 -m "DAWNLoc 0.1.0-rc.1"
git push origin v0.1.0-rc.1
```

Home Assistant reads custom app repositories directly from Git. A GitHub Release
is optional, but useful for release notes and source archives.
