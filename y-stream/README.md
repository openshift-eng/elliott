Example:

```bash
$ ./y-stream-trackers.py
CVE-2019-19335 ose-installer-container
    1778972 4.4.0 VERIFIED 
    1781946 4.3.0 CLOSED ERRATA
    1778969 4.2.z CLOSED ERRATA
    1778967 4.1.z CLOSED WONTFIX
```

4.4.0 RHSA needed? No, fixed already in prior release

```bash
CVE-2019-19330 haproxy
    1788780 4.4.0 VERIFIED 
    1781030 4.3.z CLOSED WONTFIX
    1781029 4.2.z CLOSED WONTFIX
    1781028 4.1.z CLOSED WONTFIX
```

4.4.0 RHSA needed? Yes, 4.4.0 will be the first fix

```bash
CVE-2020-8945 cri-o
    1802862 4.4.0 VERIFIED 
    1802875 4.3.z NEW 
    1802874 4.2.z NEW 
    1802847 4.1.z NEW 
```

4.4.0 RHSA needed? Yes, 4.4.0 will be the first fix
