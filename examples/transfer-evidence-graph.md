# DPA Transfer Chain Evidence Graph

**Graph status: BLOCKED**

- Review packet state: `BLOCKED`
- Blocked edges: 5
- Review edges: 0
- Graph SHA-256: `7bb14ee5df4a8148358ed8c9028e15c03c3764265a86d6b4cecb436b467cb7b6`
- External actions: disabled

## Transfer chain

```mermaid
flowchart LR
  N1["FR"]
  N2["JP"]
  N3["US"]
  N4["Analytics KK"]
  N5["Acme SaaS GmbH (synthetic)"]
  N6["Vendor Cloud Inc. (synthetic)"]
  N7["EU Hosting SARL"]
  N8["Support Tools LLC"]
  N5 -->|"appoints_processor: pass"| N6
  N6 -->|"direct_transfer_to: pass"| N1
  N6 -->|"direct_transfer_to: pass"| N2
  N6 -->|"direct_transfer_to: block"| N3
  N6 -->|"appoints_subprocessor: block"| N7
  N6 -->|"appoints_subprocessor: block"| N8
  N6 -->|"appoints_subprocessor: block"| N4
  N7 -->|"processes_in: pass"| N1
  N8 -->|"processes_in: block"| N3
  N4 -->|"processes_in: pass"| N2
```

## Weakest links

| Edge | Status | Relationship | Controls |
| --- | --- | --- | --- |
| processor-direct-to-us | block | direct_transfer_to | transfer.us |
| processor-to-subprocessor-1 | block | appoints_subprocessor | subprocessor.authorization, subprocessor.change\_notice\_and\_objection, subprocessor.flowdown |
| processor-to-subprocessor-2 | block | appoints_subprocessor | subprocessor.authorization, subprocessor.change\_notice\_and\_objection, subprocessor.flowdown, transfer.subprocessor.support\_tools\_llc |
| processor-to-subprocessor-3 | block | appoints_subprocessor | subprocessor.authorization, subprocessor.change\_notice\_and\_objection, subprocessor.flowdown, transfer.subprocessor.analytics\_kk |
| subprocessor-2-to-us | block | processes_in | transfer.subprocessor.support\_tools\_llc |

## Control remediation queue

| Control | Severity | Affected edges | Reviewer | Required evidence |
| --- | --- | ---: | --- | --- |
| subprocessor.change\_notice\_and\_objection | HIGH | 3 | Privacy Counsel | Add a clause under which the processor informs the controller of any intended addition or replacement of a sub-processor, giving the controller the opportunity to object (Art. 28(2)). |
| subprocessor.flowdown | HIGH | 3 | Privacy Counsel | Add a clause imposing materially equivalent obligations on every sub-processor (Art. 28(4)). |
| transfer.subprocessor.support\_tools\_llc | HIGH | 2 | Privacy Counsel | Confirm the transfer mechanism covering Support Tools LLC in US. |
| transfer.us | HIGH | 1 | Privacy Counsel | Document a valid Art. 46 safeguard for US (or an Art. 49 derogation) and record the basis. |

## Review gate

The graph is a deterministic reviewer aid. It does not validate a transfer mechanism, approve a sub-processor, or execute a transfer.
