#include "SynthRoadQuery.h"
#include "ZoneGraphSubsystem.h"
#include "ZoneGraphData.h"
#include "ZoneGraphTypes.h"
#include "Engine/World.h"

TArray<FSynthLaneSample> USynthRoadQuery::QueryZoneGraphLanes(UObject* WorldContextObject, FVector Center, float RadiusCm)
{
    TArray<FSynthLaneSample> Out;
    if (!WorldContextObject)
    {
        return Out;
    }
    UWorld* World = WorldContextObject->GetWorld();
    if (!World)
    {
        return Out;
    }
    UZoneGraphSubsystem* ZG = World->GetSubsystem<UZoneGraphSubsystem>();
    if (!ZG)
    {
        return Out;
    }

    const double RadiusSq = static_cast<double>(RadiusCm) * static_cast<double>(RadiusCm);
    for (const FRegisteredZoneGraphData& Reg : ZG->GetRegisteredZoneGraphData())
    {
        const AZoneGraphData* Data = Reg.ZoneGraphData;
        if (!Data || !Reg.bInUse)
        {
            continue;
        }
        const FZoneGraphStorage& Storage = Data->GetStorage();
        for (const FZoneLaneData& Lane : Storage.Lanes)
        {
            for (int32 i = Lane.PointsBegin; i < Lane.PointsEnd; ++i)
            {
                if (!Storage.LanePoints.IsValidIndex(i))
                {
                    continue;
                }
                const FVector P = Storage.LanePoints[i];
                if (FVector::DistSquaredXY(P, Center) > RadiusSq)
                {
                    continue;
                }
                FSynthLaneSample S;
                S.Position = P;
                S.Direction = Storage.LaneTangentVectors.IsValidIndex(i)
                    ? Storage.LaneTangentVectors[i].GetSafeNormal()
                    : FVector::ForwardVector;
                S.Width = Lane.Width;
                Out.Add(S);
            }
        }
    }
    return Out;
}
