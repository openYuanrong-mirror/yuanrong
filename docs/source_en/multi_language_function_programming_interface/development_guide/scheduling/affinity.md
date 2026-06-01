# Affinity

In addition to logical allocation policies for hardware resources, openYuanrong also provides rich affinity interfaces. openYuanrong implements affinity semantics based on labels. A label is an alias or marker for a minimum scheduling unit. Different nodes or instances can have the same label, and labels are represented as key-value pairs.

## Resource Labels

Resource labels are typically static labels collected when openYuanrong minimum scheduling units are created or allocated at startup. They do not change during operation due to node fault recovery or component fault restarts. Specific types include:

- Collecting node ID as a resource label: When deploying openYuanrong on a host, it will automatically obtain the value of the `NODE_ID` environment variable, using the key as `NODE_ID` and the value as `${NODE_ID}` as the node's label.
- Custom resource labels:

    When deploying openYuanrong on a host, you can customize the node's resource labels through command-line parameters, for example:

    ```shell
    yr start --master \
    -s 'function_agent.env.INIT_LABELS="{\"Product\":\"Yuanrong\", \"NodeType\":\"worker\"}"'
    ```

## Instance Labels

Instance labels are set through configuration items when creating function instances. For example: `opts.labels = ["instance:value1", "actor"]`, indicating that the created instance has two labels with key `instance` and value `value1`, and key `actor`.

## Affinity Rules

Configured affinity rules only take effect during scheduling.

An affinity rule is defined by three attributes:

- `AffinityKind`: Indicates whether it is affinity to resource labels or instance labels.
- `LabelOperator`: Indicates how to match labels, can be configured with multiple. These conditions have an AND relationship and must all be satisfied to match.
   - `LABEL_EXISTS`: The label key must exist.
   - `LABEL_NOT_EXISTS`: The label key must not exist.
   - `LABEL_IN`: The label key must exist and the value must be in the specified list.
   - `LABEL_NOT_IN`: The label key must exist and the value must not be in the specified list.
- `AffinityType`: Indicates the affinity type, including strong affinity, strong anti-affinity, weak affinity, weak anti-affinity.
   - `AffinityType.REQUIRED` and `AffinityType.REQUIRED_ANTI`: The instance must be deployed on resources that meet the conditions, otherwise it will not be deployed.
   - `AffinityType.PREFERRED` or `AffinityType.PREFERRED_ANTI`: The instance is preferentially deployed on resources that meet the conditions, but not mandatory. When resources meeting the conditions are not found, it may choose to schedule on other nodes or Pods with resources. You can enable the `preferred_anti_other_labels` configuration to directly return scheduling failure when weak affinity conditions cannot be satisfied.

A function instance can be configured with multiple affinity rules. Affinity rules with the same `AffinityKind` and `AffinityType` have an OR relationship, matching if any one is satisfied. Multiple affinity rules can also set priorities. During scheduling, they will be matched in order, prioritizing satisfaction of the earliest added affinity rules.

- `required_priority`: Strong affinity priority scheduling switch. When enabled, when multiple strong affinity conditions are passed, they are matched and scored in order. If none are satisfied, scheduling fails.
- `preferred_priority`: Weak affinity priority scheduling switch. When enabled, when multiple weak affinity conditions are passed, they are matched and scored in order. Scheduling succeeds when one is satisfied.

You can refer to the following examples to configure affinity. For more complete examples, refer to [Configuring Function Instance Affinity](../../examples/affinity.md).

Resource label affinity example:

::::{tab-set}

:::{tab-item} Python

```python
import yr

operators = [yr.LabelOperator(yr.OperatorType.LABEL_EXISTS, "key1"), yr.LabelOperator(yr.OperatorType.LABEL_EXISTS, "key2")]

# Strong resource affinity, matching resources that simultaneously contain resource label keys "key1" and "key2"
affinity1 = yr.Affinity(yr.AffinityKind.RESOURCE, yr.AffinityType.REQUIRED, operators)
# Strong resource affinity, matching resources with resource label key "key3"
affinity2 = yr.Affinity(yr.AffinityKind.RESOURCE, yr.AffinityType.REQUIRED, yr.LabelOperator(yr.OperatorType.LABEL_EXISTS, "key3"))

invokeOpt = yr.InvokeOptions()
# Resources must satisfy affinity1 or affinity2
invokeOpt.schedule_affinities = [affinity1, affinity2]
```

:::
:::{tab-item} C++

```c++
#include "yr/yr.h"

// Weak resource affinity, configuring resources with resource label key "key1"
auto affinity1 = YR::ResourcePreferredAffinity(YR::LabelExistsOperator("key1"));

// Strong resource affinity, configuring resources with resource label key "key2" and value "value1" or "value2"
auto affinity2 = YR::ResourceRequiredAffinity(YR::LabelInOperator("key2", {"value1, value2"}));

// Weak resource affinity, excluding resources with resource label key "key3"
auto affinity3 = YR::ResourcePreferredAffinity({YR::LabelDoesNotExistOperator("key3")});

// Weak resource affinity, configuring resources that simultaneously contain key "key4" and key "key5" with value "value3"
auto affinity4 = YR::ResourcePreferredAffinity({YR::LabelExistsOperator("key4"), YR::LabelNotInOperator("key5", {"value3"})});

YR::InvokeOptions opts;
// Resources must satisfy affinity2, try to satisfy affinity1 or affinity3 or affinity4
opts.AddAffinity(affinity1).AddAffinity(affinity2).AddAffinity({affinity3, affinity4});
```

:::
:::{tab-item} Java

```java
import java.util.ArrayList;
import org.yuanrong.InvokeOptions;
import org.yuanrong.affinity.*;

// Weak resource affinity, matching resources with resource label key "key1"
LabelOperator labelOperator = new LabelOperator(OperatorType.LABEL_EXISTS, "key1");
ArrayList<LabelOperator> operatorsList = new ArrayList<>();
operatorsList.add(labelOperator);
Affinity affinity = new Affinity(AffinityKind.RESOURCE, AffinityType.PREFERRED, operatorsList);

ArrayList<Affinity> affinityList = new ArrayList<>();
affinityList.add(affinity);

// Weak resource affinity, matching resources with resource label key "key2"
LabelOperator labelOperator1 = new LabelOperator(OperatorType.LABEL_EXISTS, "key2");
ArrayList<LabelOperator> operatorsList1 = new ArrayList<>();
operatorsList1.add(labelOperator1);

// Resources try to satisfy resource label key "key1" or key "key2"
InvokeOptions options = new InvokeOptions.Builder().scheduleAffinity(affinityList)
    .addResourceAffinity(AffinityType.PREFERRED, operatorsList1)
    .build();
```

:::
::::

Instance label affinity example:

::::{tab-set}

:::{tab-item} Python

```python
import yr

operators = [yr.LabelOperator(yr.OperatorType.LABEL_EXISTS, "key1"), yr.LabelOperator(yr.OperatorType.LABEL_EXISTS, "key2")]

# Strong instance affinity, matching resources that simultaneously contain instance label keys "key1" and "key2"
affinity1 = yr.Affinity(yr.AffinityKind.INSTANCE, yr.AffinityType.REQUIRED, operators)
# Strong instance affinity, matching resources containing instance label key "key3"
affinity2 = yr.Affinity(yr.AffinityKind.INSTANCE, yr.AffinityType.REQUIRED, yr.LabelOperator(yr.OperatorType.LABEL_EXISTS, "key3"))

invokeOpt = yr.InvokeOptions()
# Resources must satisfy affinity1 or affinity2
invokeOpt.schedule_affinities = [affinity1, affinity2]
```

:::
:::{tab-item} C++

```c++
#include "yr/yr.h"

// Weak instance affinity, matching resources containing instance label key "key1"
auto affinity1 = YR::InstancePreferredAffinity(YR::LabelExistsOperator("key1"));

// Strong instance affinity, configuring resources containing instance label key "key2" with value "value1" or "value2"
auto affinity2 = YR::InstanceRequiredAffinity(YR::LabelInOperator("key2", {"value1, value2"}));

YR::InvokeOptions opts;
// Resources must satisfy affinity2, try to satisfy affinity1
opts.AddAffinity(affinity1).AddAffinity(affinity2);
```

:::
:::{tab-item} Java

```java
import java.util.ArrayList;
import org.yuanrong.InvokeOptions;
import org.yuanrong.affinity.*;

// Weak instance affinity, matching resources containing instance label key "key1"
LabelOperator labelOperator = new LabelOperator(OperatorType.LABEL_EXISTS, "key1");
ArrayList<LabelOperator> operatorsList = new ArrayList<>();
operatorsList.add(labelOperator);
Affinity affinity = new Affinity(AffinityKind.RESOURCE, AffinityType.PREFERRED, operatorsList);

ArrayList<Affinity> affinityList = new ArrayList<>();
affinityList.add(affinity);

// Weak instance affinity, matching resources containing instance label key "key2"
LabelOperator labelOperator1 = new LabelOperator(OperatorType.LABEL_EXISTS, "key2");
ArrayList<LabelOperator> operatorsList1 = new ArrayList<>();
operatorsList1.add(labelOperator1);

// Resources try to satisfy instance label key "key1" or key "key2"
InvokeOptions options = new InvokeOptions.Builder().scheduleAffinity(affinityList)
    .addInstanceAffinity(AffinityType.PREFERRED, operatorsList1)
    .build();
```

:::
::::

:::{note}

- If any instance has already been scheduled and running on a node, it will not be evicted due to label changes on the runtime node. Only new instances need to match new affinity conditions.
- When requiring strong affinity or strong anti-affinity for a label, please ensure that instances or resource labels with that instance label have been created. If you want instances to have pairwise affinity, it is recommended to add affinity configuration for both instances.

:::
